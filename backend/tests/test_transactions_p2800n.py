"""P2800N end-to-end tests — same universal pipeline, different raw formats.

⚠️ Fixtures are SYNTHETIC (see tests/fixtures/README-SYNTHETIC.md).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "p2800n"

EXPECTED_TXNS = {
    "28070314063201": "COMPLETED",
    "28070314121002": "DECLINED",
    "28070314201503": "INCOMPLETE",
}


def upload_fixture_zip(client) -> dict:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fixture in sorted(FIXTURES.iterdir()):
            if fixture.is_file() and not fixture.name.endswith(".md"):
                zf.writestr(f"P2800N/{fixture.name}", fixture.read_bytes())
    buf.seek(0)
    resp = client.post(
        "/api/logs/upload",
        files={"file": ("p2800n-export.zip", buf, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def get_transactions(client, **params):
    resp = client.get("/api/transactions", params=params)
    assert resp.status_code == 200
    return resp.json()


def by_txn_id(response):
    return {item["transaction_id"]: item for item in response["items"]}


def test_p2800n_detected_and_correlated_without_p2600n_sources(client):
    """No model_code is passed: detection must identify P2800N itself."""
    upload_fixture_zip(client)
    listing = get_transactions(client)
    assert listing["total"] == 3
    found = by_txn_id(listing)
    assert set(found) == set(EXPECTED_TXNS)
    for txn_id, status in EXPECTED_TXNS.items():
        assert found[txn_id]["status"] == status
        assert found[txn_id]["model_code"] == "P2800N"


def test_p2800n_sources_are_model_specific(client):
    upload_fixture_zip(client)
    logs = client.get("/api/logs", params={"file_role": "extracted"}).json()["items"]
    sources = {f["log_source"]["code"] for f in logs if f.get("log_source")}
    assert sources == {"app", "jrn", "siu", "ifm"}
    # P2600N terminology must NOT leak into P2800N files (Phase 3 §2).
    assert "ecat" not in sources and "keeper" not in sources


def test_p2800n_successful_transaction(client):
    upload_fixture_zip(client)
    txn = by_txn_id(get_transactions(client, transaction_id="28070314063201"))["28070314063201"]
    assert txn["amount"] == 200.0
    assert txn["currency"] == "CNY"
    assert txn["start_time"] == "2026-07-03T14:06:30"
    assert txn["end_time"] == "2026-07-03T14:06:41"

    timeline = client.get(f"/api/transactions/{txn['id']}/timeline").json()
    events = [e["event"] for e in timeline["entries"]]
    assert {
        "TRANSACTION_STARTED",
        "CASH_ACCEPTED",
        "CASH_COUNTING_COMPLETED",
        "VALIDATION_PASSED",
        "HOST_REQUEST",
        "HOST_RESPONSE",
        "CASH_STORED",
        "TRANSACTION_COMPLETED",
        "SENSOR_CHANGED",
    } <= set(events)
    assert timeline["complete"] is True
    assert timeline["not_confirmed_stages"] == []


def test_p2800n_declined_via_host_result_code(client):
    upload_fixture_zip(client)
    txn = by_txn_id(get_transactions(client, transaction_id="28070314121002"))["28070314121002"]
    timeline = client.get(f"/api/transactions/{txn['id']}/timeline").json()

    declined = [e for e in timeline["entries"] if e["event"] == "HOST_DECLINED"]
    assert len(declined) == 1
    assert declined[0]["detail"]["error_code"] == "P28IFM-41"  # rc=41 captured
    assert declined[0]["raw"]["raw_text"].endswith("rc=41")
    assert timeline["transaction"]["status"] == "DECLINED"
    # Validation never confirmed for the declined flow.
    assert "validation" in {s["stage"] for s in timeline["not_confirmed_stages"]}


def test_p2800n_incomplete_with_error_code(client):
    upload_fixture_zip(client)
    txn = by_txn_id(get_transactions(client, transaction_id="28070314201503"))["28070314201503"]
    timeline = client.get(f"/api/transactions/{txn['id']}/timeline").json()

    events = [e["event"] for e in timeline["entries"]]
    assert "ERROR" in events
    assert "DEVICE_UNAVAILABLE" in events
    error_entry = next(e for e in timeline["entries"] if e["event"] == "ERROR")
    assert error_entry["detail"]["error_code"] == "P28APP-E-99"
    assert timeline["transaction"]["status"] == "INCOMPLETE"
    missing = {s["stage"] for s in timeline["not_confirmed_stages"]}
    assert "final_status" in missing


def test_p2800n_malformed_line_partial_status(client):
    upload_fixture_zip(client)
    logs = client.get("/api/logs", params={"file_role": "extracted"}).json()["items"]
    app = next(f for f in logs if "APP" in f["original_filename"])
    assert app["status"] == "PARTIAL"
    assert "1 line error" in app["status_message"]
    # Correlation still produced all three transactions.
    assert get_transactions(client)["total"] == 3


def test_p2800n_missing_log_source_still_reconstructs(client):
    """Only the application log is uploaded (no JRN/SIU/IFM)."""
    content = FIXTURES / "P2800N_APP_20260703.log"
    resp = client.post(
        "/api/logs/upload",
        files={"file": ("P2800N_APP_20260704.log", content.read_bytes(), "text/plain")},
    )
    assert resp.status_code == 201
    listing = get_transactions(client)
    found = by_txn_id(listing)
    assert set(found) == set(EXPECTED_TXNS)

    # Without IFM logs the host stages cannot be confirmed — reported, not invented.
    u1 = client.get(f"/api/transactions/{found['28070314063201']['id']}/timeline").json()
    missing = {s["stage"] for s in u1["not_confirmed_stages"]}
    assert {"host_request", "host_response"} <= missing
    assert u1["transaction"]["status"] == "COMPLETED"  # app log alone shows completion
    assert u1["complete"] is False


def test_p2800n_timestamp_mismatch_does_not_break_correlation(client):
    """Primary-key correlation tolerates skewed timestamps; window-based
    attachment does not (the skewed event must stay out)."""
    app_log = (FIXTURES / "P2800N_APP_20260703.log").read_text()
    skewed = app_log.replace(
        "<2026-07-03 14:06:40>|APP|INFO|NOTES_STORED|tid=28070314063201",
        # Journal-adjacent event with a wildly wrong clock (>24h off).
        "<2026-07-04 23:59:40>|APP|INFO|NOTES_STORED|tid=28070314063201",
    )
    assert skewed != app_log  # the fixture line we replaced existed

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("P2800N/P2800N_APP_20260705.log", skewed)
        zf.writestr("P2800N/P2800N_SIU_20260705.log", (FIXTURES / "P2800N_SIU_20260703.log").read_bytes())
    buf.seek(0)
    resp = client.post("/api/logs/upload", files={"file": ("skewed.zip", buf, "application/zip")})
    assert resp.status_code == 201

    listing = get_transactions(client)
    found = by_txn_id(listing)
    u1 = client.get(f"/api/transactions/{found['28070314063201']['id']}/timeline").json()
    stamps = [e["timestamp"] for e in u1["entries"] if e["timestamp"]]
    assert stamps == sorted(stamps), "timeline must stay chronological despite skewed clocks"
    # The skewed event still belongs to its transaction (tid key), placed last.
    assert u1["entries"][-1]["timestamp"] == "2026-07-04T23:59:40"
