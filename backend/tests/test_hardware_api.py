"""Phase 4 API tests: hardware timeline + jam classification end-to-end.

⚠️ Fixtures are SYNTHETIC (see tests/fixtures/README-SYNTHETIC.md) —
nine P2800N scenarios and two P2600N scenarios covering the required
matrix: normal transport, sensor timeout, transport timeout, possible
jam, confirmed jam, sensor mismatch, motor timeout, gate mismatch,
shutter unknown.

Both models flow through the SAME universal hardware engine; the only
difference is each model's hardware.yaml.
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


def upload_hw_zip(client, dirname: str, model_code: str | None = None):
    url = "/api/logs/upload" + (f"?model_code={model_code}" if model_code else "")
    return client.post(
        url, files={"file": (f"{dirname}.zip", _zip_bytes(dirname), "application/zip")}
    )


def hardware_of(client, transaction_id: str, model_code: str) -> dict:
    items = client.get(
        "/api/transactions", params={"model_code": model_code, "transaction_id": transaction_id}
    ).json()["items"]
    assert items, f"transaction {transaction_id} not correlated"
    return client.get(f"/api/transactions/{items[0]['id']}/hardware").json()


@pytest.fixture()
def hw2800(client):
    def _get(transaction_id):
        return hardware_of(client, transaction_id, "P2800N")

    upload_hw_zip(client, "p2800n_hw")  # model detection must identify P2800N
    return _get


@pytest.fixture()
def hw2600(client):
    def _get(transaction_id):
        return hardware_of(client, transaction_id, "P2600N")

    upload_hw_zip(client, "p2600n_hw", model_code="P2600N")
    return _get


# ---------------------------------------------------------------------------
# P2800N scenario matrix
# ---------------------------------------------------------------------------


def test_normal_transport_full_chain(hw2800):
    hw = hw2800("28070510000101")
    assert hw["final_cash_state"] == "STORED"
    assert hw["faults"][0]["classification"] == "NO_EVIDENCE_OF_JAM"
    transport = hw["transport_events"][0]
    assert transport["outcome"] == "COMPLETED"
    # cash chain includes the inferred TRANSPORTING transition
    states = [m["to_state"] for m in hw["cash_movements"]]
    assert "TRANSPORTING" in states and "ESCROW" in states
    transporting = next(m for m in hw["cash_movements"] if m["to_state"] == "TRANSPORTING")
    assert transporting["confidence"] == 0.7
    # every movement carries raw evidence
    for m in hw["cash_movements"]:
        assert m["log_file_id"] and m["line_number"] and m["raw_text"]
    # motor run is associated with its sensor transition
    motor = hw["motor_events"][0]
    assert "GATE_MAIN:CLOSED->OPEN" in motor["sensor_transitions"]
    assert motor["timed_out"] is False


def test_sensor_timeout_late_transition(hw2800):
    hw = hw2800("28070510050202")
    assert hw["transport_events"][0]["outcome"] == "MISSING_SENSOR_TRANSITION"
    sensor = hw["sensor_events"][0]
    assert sensor["expected_state"] == "OPEN"
    assert sensor["actual_state"] == "OPEN"
    assert sensor["abnormal_duration_ms"] == 17000  # 10:05:25 vs window end 10:05:08
    assert hw["faults"][0]["classification"] == "POSSIBLE_JAM"


def test_transport_timeout_probable_jam(hw2800):
    hw = hw2800("28070510100303")
    assert hw["transport_events"][0]["outcome"] == "TIMEOUT"
    assert hw["final_cash_state"] == "UNKNOWN_LOCATION"
    fault = hw["faults"][0]
    assert fault["classification"] == "PROBABLE_JAM"
    # timeout + missing expected sensor transition = two facts
    assert "no stop event was observed" in fault["statement"]
    assert "expected sensor transition(s) not observed" in fault["statement"]


def test_motor_timeout(hw2800):
    hw = hw2800("28070510150404")
    motor = next(m for m in hw["motor_events"] if m["motor"] == "STAKER")
    assert motor["timed_out"] is True
    assert motor["duration_ms"] == 25000
    assert motor["timeout_ms"] == 8000
    assert motor["transport_name"] is None
    assert hw["transport_events"] == []
    assert hw["faults"][0]["classification"] == "POSSIBLE_JAM"


def test_confirmed_jam_multi_source_evidence(hw2800):
    hw = hw2800("28070510200505")
    assert hw["final_cash_state"] == "JAMMED"
    fault = hw["faults"][0]
    assert fault["classification"] == "CONFIRMED_JAM"
    assert "confirmed by multiple independent log evidence" in fault["statement"]
    kinds = {e["kind"] for e in fault["evidence"]}
    assert {"jam_indication", "transport_timeout", "missing_sensor_transition"} <= kinds
    for e in fault["evidence"]:
        assert e["file_id"] and e["line_number"] is not None and e["raw_text"]
    # per-device temporal window override for TRANSPORT
    assert fault["analysis_window"]["before_seconds"] == 45
    assert fault["analysis_window"]["after_seconds"] == 90
    # hedged conclusion — no root-cause claim
    assert "root cause" in fault["statement"]
    assert "damaged" not in fault["statement"]


def test_sensor_mismatch_blocked_state_during_transport(hw2800):
    hw = hw2800("28070510250606")
    sensor = hw["sensor_events"][0]
    assert sensor["expected_state"] == "OPEN"
    assert sensor["actual_state"] == "CLOSED"
    assert hw["transport_events"][0]["outcome"] == "UNEXPECTED_STATE"
    assert hw["faults"][0]["classification"] == "POSSIBLE_JAM"


def test_possible_jam_repeated_movement(hw2800):
    hw = hw2800("28070510300707")
    assert len(hw["transport_events"]) == 2
    outcomes = {t["outcome"] for t in hw["transport_events"]}
    assert outcomes == {"TIMEOUT", "COMPLETED"}
    fault = hw["faults"][0]
    assert fault["classification"] == "POSSIBLE_JAM"
    assert "repeated transport start" in fault["statement"]


def test_gate_mismatch(hw2800):
    hw = hw2800("28070510350808")
    gate = hw["gate_events"][0]
    assert gate["name"] == "DIVERTER"
    assert gate["command"] == "OPEN"
    assert gate["expected_state"] == "OPEN"
    assert gate["actual_state"] == "CLOSED"
    assert gate["state_mismatch"] is True
    assert gate["position_evidence"]["raw_text"]  # position evidence preserved
    assert hw["faults"][0]["classification"] == "POSSIBLE_JAM"


def test_shutter_unknown(hw2800):
    hw = hw2800("28070510400909")
    shutter = hw["shutter_events"][0]
    assert shutter["kind"] == "shutter"
    assert shutter["command"] == "OPEN"
    assert shutter["actual_state"] is None  # position never observed — not invented
    assert shutter["timed_out"] is True
    assert hw["final_cash_state"] == "UNKNOWN_LOCATION"


# ---------------------------------------------------------------------------
# cross-model: the SAME universal hardware path for P2600N
# ---------------------------------------------------------------------------


def test_p2600n_normal_transport(hw2600):
    hw = hw2600("26070511000101")
    assert hw["final_cash_state"] == "STORED"
    assert hw["faults"][0]["classification"] == "NO_EVIDENCE_OF_JAM"
    assert hw["transport_events"][0]["outcome"] == "COMPLETED"
    motor = hw["motor_events"][0]
    assert motor["motor"] == "1" and motor["transport_name"] == "1"
    assert "S12:0->1" in motor["sensor_transitions"]


def test_p2600n_confirmed_jam(hw2600):
    hw = hw2600("26070511050202")
    assert hw["final_cash_state"] == "JAMMED"
    fault = hw["faults"][0]
    assert fault["classification"] == "CONFIRMED_JAM"
    kinds = {e["kind"] for e in fault["evidence"]}
    assert "jam_indication" in kinds and "transport_timeout" in kinds
    # jam evidence points at the Keeper line
    jam = next(e for e in fault["evidence"] if e["kind"] == "jam_indication")
    assert "jam detected in transport path" in jam["raw_text"]


# ---------------------------------------------------------------------------
# guardrails
# ---------------------------------------------------------------------------


def test_single_error_code_is_never_a_confirmed_jam(hw2800):
    # T3 has a TRANSPORT_TIMEOUT error code but no explicit jam indication.
    hw = hw2800("28070510100303")
    assert hw["faults"][0]["classification"] != "CONFIRMED_JAM"


def test_hardware_timeline_merges_everything(hw2800):
    hw = hw2800("28070510200505")
    kinds = {e["kind"] for e in hw["timeline"]}
    assert {"transaction", "cash", "motor", "transport", "fault"} <= kinds
    # chronological: timestamped entries are ordered
    stamped = [e["timestamp"] for e in hw["timeline"] if e["timestamp"] is not None]
    assert stamped == sorted(stamped)


def test_hardware_endpoint_unknown_transaction_returns_envelope(client):
    r = client.get("/api/transactions/nonexistent-id/hardware")
    assert r.status_code == 404
    body = r.json()
    assert "error" in body and body["error"]["code"]
