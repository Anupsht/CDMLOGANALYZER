"""P2600N end-to-end tests: fixture ZIP → events → transactions → timeline.

⚠️ Fixtures are SYNTHETIC (see tests/fixtures/README-SYNTHETIC.md): they
reproduce the real file inventory, not real log content. Every assertion
about field *semantics* tests the configuration, not vendor ground truth.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "p2600n"

EXPECTED_TXNS = {
    "26070310125801": "COMPLETED",
    "26070310330101": "DECLINED",
    "26070310520101": "INCOMPLETE",
}


def upload_fixture_zip(client) -> dict:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fixture in sorted(FIXTURES.iterdir()):
            if fixture.is_file() and not fixture.name.endswith(".md"):
                zf.writestr(f"P2600N/{fixture.name}", fixture.read_bytes())
    buf.seek(0)
    resp = client.post(
        "/api/logs/upload",
        files={"file": ("p2600n-export.zip", buf, "application/zip")},
        data={"model_code": "P2600N"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def get_transactions(client, **params):
    resp = client.get("/api/transactions", params=params)
    assert resp.status_code == 200
    return resp.json()


def by_txn_id(response):
    return {item["transaction_id"]: item for item in response["items"]}


def test_p2600n_zip_produces_three_transactions(client):
    upload_fixture_zip(client)
    listing = get_transactions(client, model_code="P2600N")
    assert listing["total"] == 3
    found = by_txn_id(listing)
    assert set(found) == set(EXPECTED_TXNS)
    for txn_id, status in EXPECTED_TXNS.items():
        assert found[txn_id]["status"] == status, txn_id
        assert found[txn_id]["model_code"] == "P2600N"
        assert found[txn_id]["correlation_confidence"] == 1.0  # txn-id exact


def test_successful_transaction_reconstruction(client):
    upload_fixture_zip(client)
    listing = get_transactions(client, transaction_id="26070310125801")
    txn = by_txn_id(listing)["26070310125801"]

    # Universal transaction fields (Phase 3 §7)
    assert txn["start_time"] == "2026-07-03T10:12:58.114000"
    assert txn["end_time"] == "2026-07-03T10:13:05.340000"
    assert txn["amount"] == 500.0
    assert txn["currency"] == "CNY"
    assert txn["status"] == "COMPLETED"

    detail = client.get(f"/api/transactions/{txn['id']}").json()
    assert detail["complete"] is True
    assert set(detail["stages_confirmed"]) == {
        "start",
        "cash_insertion",
        "cash_acceptance",
        "counting",
        "validation",
        "host_request",
        "host_response",
        "storage_or_return",
        "final_status",
    }
    assert detail["correlation_method"].startswith("txn_id_exact")


def test_timeline_is_chronological_with_evidence(client):
    upload_fixture_zip(client)
    txn = by_txn_id(get_transactions(client, transaction_id="26070310125801"))["26070310125801"]
    timeline = client.get(f"/api/transactions/{txn['id']}/timeline").json()

    entries = timeline["entries"]
    assert len(entries) >= 15  # eCAT + CIM + JOU + host events merged
    stamps = [e["timestamp"] for e in entries if e["timestamp"]]
    assert stamps == sorted(stamps)

    event_codes = {e["event"] for e in entries}
    assert {
        "TRANSACTION_STARTED",
        "CASH_INSERTED",
        "CASH_ACCEPTED",
        "CASH_COUNTING_COMPLETED",
        "VALIDATION_PASSED",
        "HOST_REQUEST",
        "HOST_RESPONSE",
        "CASH_STORED",
        "TRANSACTION_COMPLETED",
        "MOTOR_STARTED",
        "MOTOR_STOPPED",
        "SENSOR_CHANGED",
    } <= event_codes

    # Phase 3 §10: every real entry points back to raw evidence.
    for entry in entries:
        assert entry["raw"] is not None
        assert entry["raw"]["file_id"]
        assert entry["raw"]["line_number"] > 0
        assert entry["raw"]["raw_text"]
    assert timeline["not_confirmed_stages"] == []
    assert timeline["complete"] is True


def test_multi_log_transaction_spans_sources(client):
    upload_fixture_zip(client)
    txn = by_txn_id(get_transactions(client, transaction_id="26070310125801"))["26070310125801"]
    timeline = client.get(f"/api/transactions/{txn['id']}/timeline").json()

    source_files = {e["raw"]["file_id"] for e in timeline["entries"]}
    assert len(source_files) >= 4  # eCAT, CIM30, JOU, GRGCA10DEV
    sources = {e["source"] for e in timeline["entries"]}
    assert {"ecat", "cim", "jou", "host"} <= sources

    # Secondary correlation rules did real work: CIM motor/sensor lines carry
    # only SESSION=..., host RECV lines carry only REF=...
    assert "session_window" in txn["correlation_method"]
    assert "host_reference" in txn["correlation_method"]


def test_declined_transaction(client):
    upload_fixture_zip(client)
    txn = by_txn_id(get_transactions(client, transaction_id="26070310330101"))["26070310330101"]
    timeline = client.get(f"/api/transactions/{txn['id']}/timeline").json()

    events = [e["event"] for e in timeline["entries"]]
    assert "HOST_DECLINED" in events
    assert "CASH_RETURNED" in events
    # Decline captured from BOTH the eCAT log and the host interface log.
    assert sum(1 for e in events if e == "HOST_DECLINED") == 2

    # Cash acceptance was never confirmed for the declined flow.
    stages = {s["stage"] for s in timeline["not_confirmed_stages"]}
    assert "cash_acceptance" in stages
    assert timeline["complete"] is False


def test_incomplete_transaction_marks_missing_stages_not_confirmed(client):
    upload_fixture_zip(client)
    txn = by_txn_id(get_transactions(client, transaction_id="26070310520101"))["26070310520101"]
    timeline = client.get(f"/api/transactions/{txn['id']}/timeline").json()

    assert timeline["transaction"]["status"] == "INCOMPLETE"
    assert timeline["complete"] is False

    events = [e["event"] for e in timeline["entries"]]
    assert "TRANSACTION_STARTED" in events
    assert "DEVICE_UNAVAILABLE" in events
    assert "TRANSACTION_COMPLETED" not in events

    # Missing stages are reported, never invented.
    missing = {s["stage"] for s in timeline["not_confirmed_stages"]}
    assert {"host_request", "host_response", "final_status"} <= missing
    for marker in timeline["not_confirmed_stages"]:
        assert marker["not_confirmed"] is True
        assert marker["raw"] is None
        assert marker["event"] == "NOT_CONFIRMED"


def test_error_event_carries_mapped_error_code(client):
    upload_fixture_zip(client)
    txn = by_txn_id(get_transactions(client, transaction_id="26070310520101"))["26070310520101"]
    timeline = client.get(f"/api/transactions/{txn['id']}/timeline").json()
    # T3 is INCOMPLETE: START + CASH_INSERTED + CIM DEVICE_UNAVAILABLE.
    # No ERROR-code line exists for this txn (the Keeper EC-3301 error has
    # no transaction keys and must stay an orphan) — assert exactly that:
    # the unavailable device is reported WARNING and no ERROR is invented.
    unavailable = [e for e in timeline["entries"] if e["event"] == "DEVICE_UNAVAILABLE"]
    assert unavailable, "expected the CIM module-unavailable line"
    assert all(e["severity"] == "WARNING" for e in unavailable)
    assert not [e for e in timeline["entries"] if e["event"] == "ERROR"]

    # The orphaned Keeper error must not leak into ANY transaction.
    for other in get_transactions(client)["items"]:
        tl = client.get(f"/api/transactions/{other['id']}/timeline").json()
        assert not [e for e in tl["entries"] if (e.get("error_code") or "").startswith("EC-")], (
            "orphan Keeper error leaked into a transaction"
        )


def test_malformed_line_does_not_break_correlation(client):
    upload_fixture_zip(client)
    logs = client.get("/api/logs", params={"file_role": "extracted"}).json()["items"]
    ecat = next(f for f in logs if f["original_filename"].startswith("eCAT"))
    assert ecat["status"] == "PARTIAL"
    assert "1 line error" in ecat["status_message"]

    # Correlation still worked with the surviving 19 lines.
    listing = get_transactions(client, model_code="P2600N")
    assert listing["total"] == 3


def test_raw_evidence_matches_original_line(client):
    upload_fixture_zip(client)
    txn = by_txn_id(get_transactions(client, transaction_id="26070310125801"))["26070310125801"]
    timeline = client.get(f"/api/transactions/{txn['id']}/timeline").json()
    start_entry = next(e for e in timeline["entries"] if e["event"] == "TRANSACTION_STARTED")

    raw = start_entry["raw"]
    lines = client.get(f"/api/logs/{raw['file_id']}/lines", params={"limit": 1000}).json()
    stored = {ln["line_number"]: ln for ln in lines["items"]}
    assert raw["line_number"] in stored
    assert stored[raw["line_number"]]["raw_text"] == raw["raw_text"]
    assert raw["raw_text"] == (
        "2026-07-03 10:12:58.114 [eCAT] INFO  TRANSACTION_START TXN=26070310125801 SESSION=S000123"
    )
