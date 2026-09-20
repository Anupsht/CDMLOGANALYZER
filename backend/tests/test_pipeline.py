"""Pipeline behavior tests (status transitions, raw evidence)."""

from __future__ import annotations

import time


def _wait_terminal(client, file_id: str, timeout: float = 10.0) -> dict:
    """With the eager queue this returns immediately; kept for safety."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/logs/{file_id}/status").json()
        if status["status"] in {"COMPLETED", "PARTIAL", "FAILED"} and not status["files"]:
            return status
        children = status["files"]
        if children and all(c["status"] in {"COMPLETED", "PARTIAL", "FAILED"} for c in children):
            return status
        time.sleep(0.05)
    raise AssertionError("processing did not finish in time")


def test_txt_upload_goes_through_all_stages(client, upload_txt):
    body = upload_txt("session.log", b"2026-01-05 08:00:01 INFO start\n2026-01-05 08:00:02 INFO stop\n")
    status = _wait_terminal(client, body["id"])
    assert status["status"] == "COMPLETED"
    assert status["line_count"] == 2
    assert status["processing_started_at"] is not None
    assert status["processing_finished_at"] is not None


def test_lines_are_immutable_evidence(client, upload_txt, db_session):
    raw = b"2026-01-05 08:00:01 INFO keep me verbatim  \n"
    body = upload_txt("verbatim.log", raw)
    lines = client.get(f"/api/logs/{body['id']}/lines").json()["items"]
    # Raw text is preserved byte-for-byte (minus the line terminator)…
    assert lines[0]["raw_text"] == "2026-01-05 08:00:01 INFO keep me verbatim  "
    assert lines[0]["line_number"] == 1
    # …while the normalized structure holds the stripped text.
    assert lines[0]["normalized_data"] == {"text": "2026-01-05 08:00:01 INFO keep me verbatim"}


def test_model_detected_from_zip_path(client, db_session):
    import io
    import zipfile

    from app.models.machine import MachineModel

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("P2800N/session/ecat.log", b"plain ecat content\n")
    buf.seek(0)
    resp = client.post("/api/logs/upload", files={"file": ("p2800n-logs.zip", buf, "application/zip")})
    body = resp.json()
    _wait_terminal(client, body["id"])

    child = client.get("/api/logs", params={"file_role": "extracted"}).json()["items"][0]
    expected = db_session.query(MachineModel).filter_by(code="P2800N").one()
    assert child["machine_model_code"] == "P2800N"
    assert child["machine_model_id"] == expected.id


def test_non_log_member_stored_but_not_parsed(client):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("firmware.bin", b"\x00\x01binary")
        zf.writestr("readme.md", b"# notes")
    buf.seek(0)
    resp = client.post("/api/logs/upload", files={"file": ("bundle.zip", buf, "application/zip")})
    body = resp.json()
    _wait_terminal(client, body["id"])

    children = client.get("/api/logs", params={"file_role": "extracted"}).json()["items"]
    assert {c["original_filename"] for c in children} == {"firmware.bin", "readme.md"}
    for child in children:
        assert child["status"] == "COMPLETED"
        assert "evidence" in child["status_message"].lower()
        assert client.get(f"/api/logs/{child['id']}/lines").json()["total"] == 0
