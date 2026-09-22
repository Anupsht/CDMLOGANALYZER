"""Phase 3 §7: model-independence proof.

A P2600N transaction and a P2800N transaction must produce the *same*
universal transaction structure even though their raw logs differ
completely (different line shapes, key names, sources).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

P2600N = Path(__file__).parent / "fixtures" / "p2600n"
P2800N = Path(__file__).parent / "fixtures" / "p2800n"


def _upload_zip(client, fixture_dir: Path, inner: str, name: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fixture in sorted(fixture_dir.iterdir()):
            if fixture.is_file() and not fixture.name.endswith(".md"):
                zf.writestr(f"{inner}/{fixture.name}", fixture.read_bytes())
    buf.seek(0)
    resp = client.post("/api/logs/upload", files={"file": (name, buf, "application/zip")})
    assert resp.status_code == 201


def _timeline_of(client, txn_id: str) -> dict:
    listing = client.get("/api/transactions", params={"transaction_id": txn_id}).json()
    assert listing["total"] == 1
    return client.get(f"/api/transactions/{listing['items'][0]['id']}/timeline").json()


def test_both_models_flow_through_the_same_pipeline(client):
    _upload_zip(client, P2600N, "P2600N", "p2600n.zip")
    _upload_zip(client, P2800N, "P2800N", "p2800n.zip")

    p26 = client.get("/api/transactions", params={"model_code": "P2600N"}).json()
    p28 = client.get("/api/transactions", params={"model_code": "P2800N"}).json()
    assert p26["total"] == 3 and p28["total"] == 3

    # 1) Identical transaction object structure.
    assert set(p26["items"][0]) == set(p28["items"][0])

    # 2) Identical status vocabulary (same scenario matrix in both models).
    assert {i["status"] for i in p26["items"]} == {"COMPLETED", "DECLINED", "INCOMPLETE"}
    assert {i["status"] for i in p28["items"]} == {"COMPLETED", "DECLINED", "INCOMPLETE"}

    # 3) Identical confidence and method semantics.
    for items in (p26["items"], p28["items"]):
        for item in items:
            assert item["correlation_confidence"] == 1.0
            assert item["correlation_method"].startswith("txn_id_exact")


def test_universal_event_vocabulary_is_shared(client):
    _upload_zip(client, P2600N, "P2600N", "p2600n.zip")
    _upload_zip(client, P2800N, "P2800N", "p2800n.zip")

    t26 = _timeline_of(client, "26070310125801")
    t28 = _timeline_of(client, "28070314063201")

    # Both timelines use the same entry schema...
    assert set(t26["entries"][0]) == set(t28["entries"][0])
    # ...the same universal stage vocabulary: each model's successful
    # transaction confirms ALL nine lifecycle stages of the reconstruction.
    stages26 = set(t26["stages_confirmed"]) | set(t26["stages_not_confirmed"])
    stages28 = set(t28["stages_confirmed"]) | set(t28["stages_not_confirmed"])
    assert stages26 == stages28
    assert stages26 == {
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
    assert t26["stages_not_confirmed"] == [] and t28["stages_not_confirmed"] == []
    # ...and overlapping universal event codes, without any raw P2600N or
    # P2800N message leaking through as an event name.
    shared = {e["event"] for e in t26["entries"]} & {e["event"] for e in t28["entries"]}
    assert {
        "TRANSACTION_STARTED",
        "CASH_ACCEPTED",
        "HOST_REQUEST",
        "HOST_RESPONSE",
        "CASH_STORED",
        "TRANSACTION_COMPLETED",
    } <= shared
    for entry in t26["entries"] + t28["entries"]:
        assert entry["event"] in {code for code in shared} | {
            "CASH_INSERTED",
            "CASH_COUNTING_COMPLETED",
            "VALIDATION_PASSED",
            "HOST_DECLINED",
            "CASH_RETURNED",
            "DEVICE_UNAVAILABLE",
            "MOTOR_STARTED",
            "MOTOR_STOPPED",
            "SENSOR_CHANGED",
            "ERROR",
            "UNMAPPED",
            "UNKNOWN",
        }


def test_raw_formats_differ_but_structure_matches(client):
    _upload_zip(client, P2600N, "P2600N", "p2600n.zip")
    _upload_zip(client, P2800N, "P2800N", "p2800n.zip")

    t26 = _timeline_of(client, "26070310125801")
    t28 = _timeline_of(client, "28070314063201")

    raw26 = {e["raw"]["raw_text"] for e in t26["entries"]}
    raw28 = {e["raw"]["raw_text"] for e in t28["entries"]}
    assert raw26 and raw28
    assert raw26.isdisjoint(raw28)  # completely different raw material…

    # …mapped onto the same normalized shape (event/device/severity/stage/raw).
    for entry in t26["entries"] + t28["entries"]:
        assert set(entry) == {"timestamp", "event", "stage", "device", "severity",
                              "source", "detail", "not_confirmed", "raw"}
        assert entry["severity"] in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def test_each_model_uses_its_own_parsers(client):
    """Adapter-scoped parsers: P2600N parsers must never parse P2800N files."""
    _upload_zip(client, P2600N, "P2600N", "p2600n.zip")
    _upload_zip(client, P2800N, "P2800N", "p2800n.zip")

    logs = client.get("/api/logs", params={"file_role": "extracted", "limit": 50}).json()["items"]
    parsers_by_model = {}
    for log in logs:
        if log["machine_model_code"]:
            parsers_by_model.setdefault(log["machine_model_code"], set()).add(log["parser_code"])

    assert parsers_by_model["P2600N"], "P2600N files must record parsers"
    assert parsers_by_model["P2800N"], "P2800N files must record parsers"
    assert parsers_by_model["P2600N"].isdisjoint(parsers_by_model["P2800N"])
    assert all(code.startswith("p2600n_") for code in parsers_by_model["P2600N"])
    assert all(code.startswith("p2800n_") for code in parsers_by_model["P2800N"])
