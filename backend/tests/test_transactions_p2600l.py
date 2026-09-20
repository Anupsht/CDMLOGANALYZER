"""Phase 6 tests: P2600L — third model through the universal engine.

⚠️ Fixtures are SYNTHETIC (see tests/fixtures/README-SYNTHETIC.md) — no
real P2600L logs or documentation has been received; the P2600L config
package is a labeled placeholder built WITHOUT inferring behaviour from
P2600N (own sources apl/jal/dgn, own tokens).

Completion criterion demonstrated: P2600L → Adapter → Universal Engine
with the same API/data model as P2600N and P2800N.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class ModelSession:
    """TestClient + transaction lookup for one uploaded model's fixtures."""

    def __init__(self, client, model_code: str):
        self.client = client
        self.model_code = model_code

    def txn(self, transaction_id: str) -> dict:
        items = self.client.get(
            "/api/transactions",
            params={"model_code": self.model_code, "transaction_id": transaction_id},
        ).json()["items"]
        assert items, f"transaction {transaction_id} not correlated"
        return items[0]

    def hardware(self, transaction_id: str) -> dict:
        return self.client.get(f"/api/transactions/{self.txn(transaction_id)['id']}/hardware").json()

    def diagnostics(self, transaction_id: str) -> dict:
        return self.client.get(
            f"/api/transactions/{self.txn(transaction_id)['id']}/diagnostics"
        ).json()


def upload_zip(client, dirname: str, model_code: str | None = None) -> dict:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fixture in sorted((FIXTURES / dirname).iterdir()):
            if fixture.is_file() and not fixture.name.endswith(".md"):
                zf.writestr(f"{dirname}/{fixture.name}", fixture.read_bytes())
    buf.seek(0)
    url = "/api/logs/upload" + (f"?model_code={model_code}" if model_code else "")
    return client.post(url, files={"file": (f"{dirname}.zip", buf, "application/zip")}).json()


@pytest.fixture()
def p2600l(client) -> ModelSession:
    # No model_code form field: auto-detection must identify P2600L.
    upload_zip(client, "p2600l")
    return ModelSession(client, "P2600L")


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------


def test_p2600l_detected_without_model_code(client, p2600l):
    logs = client.get("/api/logs", params={"file_role": "extracted"}).json()["items"]
    assert logs, "files extracted"
    for log in logs:
        assert log["machine_model_code"] == "P2600L"
    evidence = client.get(f"/api/logs/{logs[0]['id']}").json()["detection_evidence"]
    candidates = evidence["candidates"]
    assert candidates and candidates[0]["model_code"] == "P2600L"
    # multi-signal evidence: filename + at least one corroborating signal
    sources = {e["source"] for c in candidates for e in c["evidence"]}
    assert "filename" in sources
    assert sources & {"content_signature", "software_identifier", "device_name"}


def test_p2600l_sources_are_its_own_not_p2600n(client, p2600l):
    logs = client.get("/api/logs", params={"file_role": "extracted"}).json()["items"]
    sources = {(f.get("log_source") or {}).get("code") for f in logs}
    assert sources == {"apl", "dgn", "jal"}  # P2600L's own source set
    assert sources.isdisjoint({"ecat", "cim", "keeper", "jou", "noteinfo"})  # not P2600N
    assert sources.isdisjoint({"app", "jrn", "siu", "ifm"})  # not P2800N


# ---------------------------------------------------------------------------
# the three scenarios through the universal engine
# ---------------------------------------------------------------------------


def test_p2600l_successful_transaction(p2600l):
    txn = p2600l.txn("T-8801")
    assert txn["status"] == "COMPLETED"
    assert txn["amount"] == 100.0 and txn["currency"] == "CNY"
    assert txn["correlation_confidence"] == 1.0
    hw = p2600l.hardware("T-8801")
    assert hw["final_cash_state"] == "STORED"
    states = [m["to_state"] for m in hw["cash_movements"]]
    assert "TRANSPORTING" in states  # Phase 4 chain works for P2600L too
    d = p2600l.diagnostics("T-8801")
    assert d["diagnosis_class"] == "NO_FAILURE"
    assert d["final_cash_state"] == "STORED"


def test_p2600l_host_decline_is_host_failure(p2600l):
    txn = p2600l.txn("T-8802")
    assert txn["status"] == "DECLINED"
    d = p2600l.diagnostics("T-8802")
    assert d["classification"] == "HOST_TRANSACTION_FAILURE"
    assert d["diagnosis_class"] == "HOST_FAILURE"
    assert not [f for f in d["findings"] if f["diagnosis_class"] == "HARDWARE_FAILURE"]
    assert p2600l.hardware("T-8802")["final_cash_state"] == "RETURNED"


def test_p2600l_confirmed_jam(p2600l):
    txn = p2600l.txn("T-8803")
    assert txn["status"] == "FAILED"
    d = p2600l.diagnostics("T-8803")
    assert d["classification"] == "CONFIRMED_CASH_JAM"
    assert d["diagnosis_class"] == "HARDWARE_FAILURE"
    assert d["confidence"] == "VERY_HIGH"
    assert p2600l.hardware("T-8803")["final_cash_state"] == "JAMMED"
    finding = next(f for f in d["findings"] if f["rule_id"] == "CONFIRMED_CASH_JAM")
    raw_refs = [e for e in finding["evidence"] if e.get("raw_text")]
    assert raw_refs and any("jam detected" in e["raw_text"] for e in raw_refs)


def test_p2600l_malformed_line_partial(client, p2600l):
    logs = client.get("/api/logs", params={"file_role": "extracted"}).json()["items"]
    apl = next(f for f in logs if f["original_filename"].endswith("APL_20260801.log"))
    assert apl["status"] == "PARTIAL"  # malformed line handled safely


# ---------------------------------------------------------------------------
# same dashboard/API/data model as the other models
# ---------------------------------------------------------------------------


def test_p2600l_config_endpoint(client):
    r = client.get("/api/models/P2600L/config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["model_code"] == "P2600L"
    assert cfg["enabled"] is True and cfg["placeholder"] is False
    assert cfg["config_package_present"] is True
    assert {s["source"] for s in cfg["log_sources"]} == {"apl", "dgn", "jal"}
    assert all(s["parser"] for s in cfg["log_sources"])
    assert cfg["hardware"]["present"] is True
    assert cfg["diagnostics"]["rules"]  # universal rules apply via overlay merge
    assert cfg["error_patterns"]
