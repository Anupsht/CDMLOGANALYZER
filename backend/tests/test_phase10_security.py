"""Phase 10 — security hardening: headers, rate limiting, malicious files."""

from __future__ import annotations

import io
import zipfile

import pytest


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _login(client, username="admin", password="Admin#12345") -> dict:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ---- security headers ---------------------------------------------------------------


def test_security_headers_on_api_responses(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


# ---- rate limiting --------------------------------------------------------------------


def _find_limiter(app):
    stack = app.middleware_stack
    while stack is not None:
        if type(stack).__name__ == "RateLimitMiddleware":
            return stack
        stack = getattr(stack, "app", None)
    return None


def test_login_rate_limit_returns_429(auth_client):
    from app.core.config import get_settings
    from app.main import app

    limiter = _find_limiter(app)
    assert limiter is not None
    limiter._hits.clear()
    settings = get_settings()
    original = settings.rate_limit_auth_per_minute
    settings.rate_limit_auth_per_minute = 3
    try:
        codes = [
            auth_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "bad-pass-1"},
            ).status_code
            for _ in range(4)
        ]
        assert codes[:3] == [401, 401, 401]
        assert codes[3] == 429
        blocked = auth_client.get("/api/transactions")
        assert blocked.status_code == 401  # api bucket untouched by auth bucket
    finally:
        settings.rate_limit_auth_per_minute = original
        limiter._hits.clear()


def test_rate_limiter_window_logic():
    from app.core.hardening import RateLimitMiddleware

    limiter = RateLimitMiddleware(app=None)
    assert [limiter._allow("t:1", 2) for _ in range(3)] == [True, True, False]
    assert limiter._allow("t:2", 2) is True  # independent key


# ---- malicious / malformed uploads ------------------------------------------------------


def _upload(client, headers, name: str, content: bytes):
    return client.post(
        "/api/logs/upload",
        headers=headers,
        files={"file": (name, content, "application/octet-stream")},
    )


def _status(client, headers, file_id: str) -> dict:
    resp = client.get(f"/api/logs/{file_id}", headers=headers)
    assert resp.status_code == 200
    return resp.json()


def test_zip_path_traversal_member_rejected(client):
    h = _login(client)
    evil = _zip_bytes({"../../evil.log": b"gotcha"})
    resp = _upload(client, h, "traversal.zip", evil)
    assert resp.status_code == 201  # stored; pipeline rejects it safely
    row = _status(client, h, resp.json()["id"])
    assert row["status"] == "FAILED"
    assert "Unsafe relative path" in (row["status_message"] or "") or "unsafe" in (
        row["status_message"] or ""
    ).lower()


def test_zip_bomb_ratio_rejected(client):
    h = _login(client)
    bomb = _zip_bytes({"zeros.log": b"\x00" * (8 * 1024 * 1024)})
    resp = _upload(client, h, "bomb.zip", bomb)
    assert resp.status_code == 201
    row = _status(client, h, resp.json()["id"])
    assert row["status"] == "FAILED"
    assert "bomb" in (row["status_message"] or "").lower() or "ratio" in (
        row["status_message"] or ""
    ).lower()


def test_executable_member_extension_rejected(client):
    h = _login(client)
    evil = _zip_bytes({"payload.exe": b"MZfakebinary", "notes.log": b"2026-01-01 INFO ok"})
    resp = _upload(client, h, "payloads.zip", evil)
    assert resp.status_code == 201
    row = _status(client, h, resp.json()["id"])
    assert row["status"] == "FAILED"
    assert "forbidden file type" in (row["status_message"] or "")


def test_fake_zip_magic_byte_check(client):
    h = _login(client)
    resp = _upload(client, h, "not-a-zip.zip", b"this is definitely not a zip archive")
    assert resp.status_code == 422
    assert "not a valid ZIP" in resp.json()["error"]["message"]


def test_forbidden_upload_extension(client):
    h = _login(client)
    resp = _upload(client, h, "ransomware.exe", b"MZ")
    assert resp.status_code == 415


def test_upload_size_limit_enforced(client):
    h = _login(client)
    from app.core.config import get_settings

    limit = get_settings().max_upload_size_bytes
    resp = _upload(client, h, "big.log", b"x" * (limit + 1024))
    assert resp.status_code == 413


def test_path_traversal_filename_sanitized(client):
    h = _login(client)
    resp = _upload(client, h, "../../etc/passwd.log", b"2026-01-05 08:00:01 INFO ok\n")
    assert resp.status_code == 201
    body = resp.json()
    stored_name = body.get("original_filename") or body.get("stored_filename") or ""
    assert ".." not in stored_name and "/" not in stored_name


def test_storage_files_stay_under_storage_root(client, db_session):
    from pathlib import Path

    from app.core.config import get_settings
    from app.models.log_file import LogFile
    from app.utils.file_storage import FileStorage

    h = _login(client)
    resp = _upload(client, h, "isolation.log", b"2026-01-05 08:00:01 INFO ok\n")
    assert resp.status_code == 201
    row = db_session.query(LogFile).order_by(LogFile.created_at.desc()).first()
    storage = FileStorage()
    resolved = storage.resolve(row.file_path)
    assert resolved.is_relative_to(storage.root)
    # resolve() refuses escapes
    with pytest.raises(Exception):
        storage.resolve("../../outside.log")
    assert get_settings().storage_dir
