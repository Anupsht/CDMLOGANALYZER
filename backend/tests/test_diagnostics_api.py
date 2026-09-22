"""Phase 5 API tests: diagnostics report endpoint end-to-end.

⚠️ Fixtures are SYNTHETIC (see tests/fixtures/README-SYNTHETIC.md).
Runs the full chain Upload → Detection → Adapter → Parser → Normalized
Events → Correlation → Hardware → Diagnostics and checks the report
structure + the required golden behaviours on real fixture scenarios.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _zip_bytes(dirname: str) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fixture in sorted((FIXTURES / dirname).iterdir()):
            if fixture.is_file() and not fixture.name.endswith(".md"):
                zf.writestr(f"{dirname}/{fixture.name}", fixture.read_bytes())
    buf.seek(0)
    return buf


def upload_zip(client, dirname: str, model_code: str | None = None):
    url = "/api/logs/upload" + (f"?model_code={model_code}" if model_code else "")
    return client.post(
        url, files={"file": (f"{dirname}.zip", _zip_bytes(dirname), "application/zip")}
    )


def diagnostics_of(client, transaction_id: str, model_code: str) -> dict:
    items = client.get(
        "/api/transactions", params={"model_code": model_code, "transaction_id": transaction_id}
    ).json()["items"]
    assert items, f"transaction {transaction_id} not correlated"
    return client.get(f"/api/transactions/{items[0]['id']}/diagnostics").json()


@pytest.fixture()
def hw2800(client):
    def _get(transaction_id):
        return diagnostics_of(client, transaction_id, "P2800N")

    upload_zip(client, "p2800n_hw")
    return _get


@pytest.fixture()
def p2600(client):
    def _get(transaction_id):
        return diagnostics_of(client, transaction_id, "P2600N")

    upload_zip(client, "p2600n", model_code="P2600N")
    return _get


# ---------------------------------------------------------------------------
# structure (section 10) + section 3 finding structure
# ---------------------------------------------------------------------------


def test_report_structure_complete(hw2800):
    report = hw2800("28070510200505")
    # section 10 output fields
    for key in (
        "summary", "classification", "severity", "confidence",
        "findings", "transaction", "final_cash_state",
    ):
        assert key in report
    finding = next(f for f in report["findings"] if f["rule_id"] == "CONFIRMED_CASH_JAM")
    # section 3 finding structure
    for key in (
        "finding_id", "category", "severity", "confidence", "summary",
        "interpretation", "possible_causes", "recommended_action", "evidence",
    ):
        assert key in finding and finding[key] is not None
    # section 4: evidence references raw lines (via the flattened Phase 4
    # fault evidence and the rule's own matched events)
    assert finding["evidence"]
    raw_refs = [e for e in finding["evidence"] if e.get("raw_text")]
    assert raw_refs
    for e in raw_refs:
        assert e["file_id"] and e["line_number"] is not None
    # cash states of the transaction are attached
    assert finding["cash_states"] == ["ACCEPTED", "COUNTED", "TRANSPORTING", "JAMMED"]


# ---------------------------------------------------------------------------
# golden behaviours on fixture scenarios
# ---------------------------------------------------------------------------


def test_confirmed_jam_classification(hw2800):
    report = hw2800("28070510200505")
    assert report["classification"] == "CONFIRMED_CASH_JAM"
    assert report["diagnosis_class"] == "HARDWARE_FAILURE"
    assert report["severity"] == "CRITICAL"
    assert report["confidence"] == "VERY_HIGH"
    assert report["final_cash_state"] == "JAMMED"


def test_normal_transport_no_failure(hw2800):
    report = hw2800("28070510000101")
    assert report["diagnosis_class"] == "NO_FAILURE"
    assert any(f["rule_id"] == "NORMAL_COMPLETION" for f in report["findings"])
    assert not [f for f in report["findings"] if f["diagnosis_class"] == "HARDWARE_FAILURE"]


def test_transport_timeout_is_probable_jam_not_confirmed(hw2800):
    # T3: transport timeout + missing sensor transition, NO explicit jam code
    report = hw2800("28070510100303")
    ids = [f["rule_id"] for f in report["findings"]]
    assert "POSSIBLE_CASH_JAM" in ids
    assert "CONFIRMED_CASH_JAM" not in ids  # a single error code never confirms
    finding = next(f for f in report["findings"] if f["rule_id"] == "POSSIBLE_CASH_JAM")
    assert finding["confidence"] in ("MODERATE", "HIGH")


def test_shutter_unknown_produces_cash_and_application_findings(hw2800):
    # T9: transaction completed OK while shutter position stayed unknown and
    # cash never reached a terminal state → mismatch + accepted-not-stored.
    report = hw2800("28070510400909")
    ids = [f["rule_id"] for f in report["findings"]]
    assert "TRANSACTION_OUTCOME_MISMATCH" in ids
    assert "CASH_ACCEPTED_NOT_STORED" in ids
    assert "SHUTTER_ANOMALY" in ids


def test_p2600n_host_decline_is_host_failure(p2600):
    report = p2600("26070310330101")
    assert report["classification"] == "HOST_TRANSACTION_FAILURE"
    assert report["diagnosis_class"] == "HOST_FAILURE"
    finding = next(f for f in report["findings"] if f["rule_id"] == "HOST_TRANSACTION_FAILURE")
    assert finding["category"] == "HOST"
    # evidence includes the actual HOST_DECLINED line
    ev_codes = {e.get("event") for e in finding["evidence"] if e.get("kind") == "event"}
    assert "HOST_DECLINED" in ev_codes
    assert not [f for f in report["findings"] if f["diagnosis_class"] == "HARDWARE_FAILURE"]


def test_p2600n_successful_deposit_no_failure(p2600):
    report = p2600("26070310125801")
    assert report["diagnosis_class"] == "NO_FAILURE"
    assert report["final_cash_state"] == "STORED"
    # amount reconciliation ran (both sides present in eCAT logs) with no mismatch
    assert "CASH_AMOUNT_MISMATCH" not in [f["rule_id"] for f in report["findings"]]


# ---------------------------------------------------------------------------
# robustness
# ---------------------------------------------------------------------------


def test_report_recomputes_after_findings_deleted(client, db_session):
    """The report is recomputed on read (rule/config changes + recovery
    visibility), so deleting stored findings is self-healing."""
    from app.models.diagnostics import DiagnosticFinding

    upload_zip(client, "p2800n_hw")
    items = client.get(
        "/api/transactions", params={"model_code": "P2800N", "transaction_id": "28070510200505"}
    ).json()["items"]
    txn_id = items[0]["id"]
    assert client.get(f"/api/transactions/{txn_id}/diagnostics").json()["findings"]

    db_session.query(DiagnosticFinding).delete()
    db_session.commit()

    report = client.get(f"/api/transactions/{txn_id}/diagnostics").json()
    assert report["classification"] == "CONFIRMED_CASH_JAM"
    assert report["findings"]


def test_unknown_transaction_returns_error_envelope(client):
    r = client.get("/api/transactions/nonexistent/diagnostics")
    assert r.status_code == 404
    body = r.json()
    assert "error" in body and body["error"]["code"]


def test_rule_config_change_reflected_in_report(client, hw2800):
    """Rules are data: disabling the jam rule changes the report — proof the
    engine is config-driven, not hard-coded."""
    from app.core.model_config import reload_model_configs
    from app.analysis.diagnostics import DiagnosticConfig, engine_for

    items = client.get(
        "/api/transactions", params={"model_code": "P2800N", "transaction_id": "28070510200505"}
    ).json()["items"]
    txn_id = items[0]["id"]

    rules_path = FIXTURES.parent.parent.parent / "config" / "diagnostics" / "rules.yaml"
    original = rules_path.read_text()
    try:
        rules_path.write_text(
            original.replace("  - id: CONFIRMED_CASH_JAM", "  - id: CONFIRMED_CASH_JAM\n    enabled: false", 1)
        )
        reload_model_configs()
        report = client.get(f"/api/transactions/{txn_id}/diagnostics").json()
        assert "CONFIRMED_CASH_JAM" not in [f["rule_id"] for f in report["findings"]]
        # the transport-obstruction evidence still classifies the fault
        assert report["findings"]
    finally:
        rules_path.write_text(original)
        reload_model_configs()
    # restored config → finding back
    report = client.get(f"/api/transactions/{txn_id}/diagnostics").json()
    assert "CONFIRMED_CASH_JAM" in [f["rule_id"] for f in report["findings"]]
