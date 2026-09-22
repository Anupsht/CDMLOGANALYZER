"""Upload API tests: validation, metadata, duplicates, size limits."""

from __future__ import annotations

import hashlib


def test_upload_txt_log_succeeds(client, upload_txt):
    body = upload_txt("session1.log", b"2026-01-05 08:00:01 INFO boot\n")
    assert body["original_filename"] == "session1.log"
    assert body["file_type"] == "log"
    assert body["file_role"] == "upload"
    assert body["size_bytes"] == len(b"2026-01-05 08:00:01 INFO boot\n")
    assert body["checksum_sha256"] == hashlib.sha256(
        b"2026-01-05 08:00:01 INFO boot\n"
    ).hexdigest()
    assert body["stored_filename"].startswith(body["id"])
    assert body["status"] == "COMPLETED"  # eager queue processed synchronously


def test_upload_all_supported_extensions(client):
    for name in ("a.txt", "b.log", "c.csv", "d.json"):
        resp = client.post("/api/logs/upload", files={"file": (name, b"data", "text/plain")})
        assert resp.status_code == 201, f"{name}: {resp.text}"


def test_upload_rejects_unsupported_extension(client):
    resp = client.post("/api/logs/upload", files={"file": ("evil.exe", b"MZ...", "application/octet-stream")})
    assert resp.status_code == 415
    error = resp.json()["error"]
    assert error["code"] == "unsupported_file_type"


def test_upload_rejects_oversize(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 0)
    resp = client.post(
        "/api/logs/upload", files={"file": ("big.log", b"more than zero bytes", "text/plain")}
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "file_too_large"
    assert resp.json()["error"]["message"]  # clean message, no traceback


def test_duplicate_detection(client, upload_txt):
    content = b"2026-01-05 08:00:01 INFO duplicate me\n"
    first = upload_txt("first.log", content)
    second = upload_txt("second.log", content)

    assert first["duplicate_of_id"] is None
    assert second["duplicate_of_id"] == first["id"]
    assert second["is_duplicate"] is True

    # Both files exist independently (both preserved on disk/metadata).
    listing = client.get("/api/logs").json()
    assert listing["total"] == 2


def test_upload_with_machine_and_model_links(client, upload_txt, db_session):
    from app.models.machine import Machine, MachineModel

    model = db_session.query(MachineModel).filter_by(code="P2600N").one()
    machine = Machine(serial_number="GRG-0001", machine_model_id=model.id, location="Branch 12")
    db_session.add(machine)
    db_session.commit()

    body = upload_txt("linked.log", b"data", machine_id=machine.id)
    assert body["machine_id"] == machine.id
    assert body["machine_model_code"] == "P2600N"


def test_upload_with_unknown_machine_404(client):
    resp = client.post(
        "/api/logs/upload",
        files={"file": ("x.log", b"x", "text/plain")},
        data={"machine_id": "does-not-exist"},
    )
    assert resp.status_code == 404


def test_upload_requires_file(client):
    resp = client.post("/api/logs/upload")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert "request_id" in body


def test_original_file_stored_and_untouched(client, upload_txt):
    from app.core.config import get_settings
    from pathlib import Path

    content = b"2026-01-05 08:00:01 INFO raw storage\n"
    body = upload_txt("raw.log", content)
    storage_root = Path(get_settings().storage_dir)
    matches = list(storage_root.rglob(body["stored_filename"]))
    assert len(matches) == 1, f"stored file not found: {body['stored_filename']}"
    assert matches[0].read_bytes() == content
    assert matches[0].is_relative_to(storage_root / "uploads" / "original")
