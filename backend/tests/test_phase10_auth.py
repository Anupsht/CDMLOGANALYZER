"""Phase 10 — authentication: hashing, sessions, expiry, lockout, policy."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.security import hash_password, password_violations, verify_password

ADMIN = ("admin", "Admin#12345")


def _login(client, username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- password hashing primitives ---------------------------------------------


def test_passwords_never_stored_plaintext(db_session):
    from app.models.user import User

    row = db_session.query(User).filter(User.username == ADMIN[0]).one()
    assert row.password_hash is not None
    assert ADMIN[1] not in row.password_hash
    assert row.password_hash.startswith("pbkdf2_sha256$")
    assert verify_password(ADMIN[1], row.password_hash)
    assert not verify_password("wrong", row.password_hash)


def test_hash_is_salted():
    a, b = hash_password("SamePassword123"), hash_password("SamePassword123")
    assert a != b, "identical passwords must produce different hashes (salted)"


def test_password_policy_rules():
    settings_iterations_backup = None  # policy is iteration-independent
    assert password_violations("short1A")  # too short
    assert password_violations("alllowercase123")  # no upper
    assert password_violations("ALLUPPERCASE123")  # no lower
    assert password_violations("NoDigitsHere")  # no digit
    assert password_violations("OkPassword12") == []


# ---- login / session lifecycle -------------------------------------------------


def test_login_success_and_me(auth_client):
    resp = _login(auth_client, *ADMIN)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "ADMIN"
    assert len(body["token"]) >= 32
    me = auth_client.get("/api/auth/me", headers=_headers(body["token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


def test_login_failure_is_generic_and_audited(auth_client, db_session):
    resp = _login(auth_client, ADMIN[0], "DefinitelyWrong#1")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    entry = (
        db_session.query(__import__("app.models.audit", fromlist=["AuditLog"]).AuditLog)
        .filter_by(action="auth.login_failed", result="failure")
        .one_or_none()
    )
    assert entry is not None
    assert entry.entity_id == ADMIN[0]


def test_unknown_user_same_error_as_wrong_password(auth_client):
    assert _login(auth_client, "nosuchuser", "Whatever#1").status_code == 401
    assert _login(auth_client, ADMIN[0], "Whatever#1").status_code == 401


def test_account_lockout_after_repeated_failures(auth_client):
    for _ in range(5):
        assert _login(auth_client, ADMIN[0], "Wrong#Password1").status_code == 401
    # Even the correct password is rejected while locked.
    locked = _login(auth_client, *ADMIN)
    assert locked.status_code == 423
    assert locked.json()["error"]["code"] == "account_locked"


def test_disabled_user_cannot_login(auth_client, db_session):
    from app.models.user import User

    user = db_session.query(User).filter(User.username == "viewer").one()
    user.is_active = False
    db_session.commit()
    assert _login(auth_client, "viewer", "Viewer#12345").status_code == 401


def test_logout_revokes_session(auth_client):
    token = _login(auth_client, *ADMIN).json()["token"]
    assert auth_client.get("/api/auth/me", headers=_headers(token)).status_code == 200
    assert auth_client.post("/api/auth/logout", headers=_headers(token)).status_code == 204
    assert auth_client.get("/api/auth/me", headers=_headers(token)).status_code == 401


def test_expired_session_rejected(auth_client, db_session):
    from app.core.security import hash_token, new_session_token
    from app.models.auth_session import AuthSession
    from app.models.user import User

    user = db_session.query(User).filter(User.username == ADMIN[0]).one()
    token = new_session_token()
    db_session.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.utcnow() - timedelta(minutes=1),
        )
    )
    db_session.commit()
    assert auth_client.get("/api/auth/me", headers=_headers(token)).status_code == 401


def test_missing_or_malformed_token_401(auth_client):
    assert auth_client.get("/api/auth/me").status_code == 401
    assert auth_client.get("/api/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401
    assert auth_client.get(
        "/api/auth/me", headers={"Authorization": "Bearer deadbeef"}
    ).status_code == 401


# ---- password change ------------------------------------------------------------


def test_change_password_requires_old_password_and_policy(auth_client):
    token = _login(auth_client, *ADMIN).json()["token"]
    h = _headers(token)
    bad_old = auth_client.post(
        "/api/auth/change-password",
        headers=h,
        json={"old_password": "nope", "new_password": "NewPass#12345"},
    )
    assert bad_old.status_code == 422
    weak = auth_client.post(
        "/api/auth/change-password",
        headers=h,
        json={"old_password": ADMIN[1], "new_password": "weak"},
    )
    assert weak.status_code == 422
    assert "policy" in weak.json()["error"]["message"].lower()


def test_change_password_revokes_other_sessions(auth_client):
    token_a = _login(auth_client, *ADMIN).json()["token"]
    token_b = _login(auth_client, *ADMIN).json()["token"]
    resp = auth_client.post(
        "/api/auth/change-password",
        headers=_headers(token_a),
        json={"old_password": ADMIN[1], "new_password": "BrandNew#99"},
    )
    assert resp.status_code == 204
    # session A (used for the change) still valid; session B revoked.
    assert auth_client.get("/api/auth/me", headers=_headers(token_a)).status_code == 200
    assert auth_client.get("/api/auth/me", headers=_headers(token_b)).status_code == 401
    # old password no longer accepted; new one works.
    assert _login(auth_client, ADMIN[0], ADMIN[1]).status_code == 401
    assert _login(auth_client, ADMIN[0], "BrandNew#99").status_code == 200


# ---- user administration (users:manage) ------------------------------------------


def test_admin_creates_user_and_duplicate_rejected(auth_client):
    token = _login(auth_client, *ADMIN).json()["token"]
    h = _headers(token)
    created = auth_client.post(
        "/api/auth/users",
        headers=h,
        json={"username": "new.tech", "password": "Strong#12345", "role": "TECHNICIAN"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "TECHNICIAN"
    dup = auth_client.post(
        "/api/auth/users",
        headers=h,
        json={"username": "new.tech", "password": "Strong#12345", "role": "VIEWER"},
    )
    assert dup.status_code == 409
    weak = auth_client.post(
        "/api/auth/users",
        headers=h,
        json={"username": "weak.guy", "password": "weak", "role": "VIEWER"},
    )
    assert weak.status_code == 422
    bad_role = auth_client.post(
        "/api/auth/users",
        headers=h,
        json={"username": "odd.role", "password": "Strong#12345", "role": "WIZARD"},
    )
    assert bad_role.status_code == 422


def test_admin_can_reset_password_and_update_role(auth_client):
    token = _login(auth_client, *ADMIN).json()["token"]
    h = _headers(token)
    reset = auth_client.post(
        "/api/auth/users/viewer/reset-password", headers=h, json={"new_password": "Fresh#12345"}
    )
    assert reset.status_code == 204
    assert _login(auth_client, "viewer", "Fresh#12345").status_code == 200
    assert _login(auth_client, "viewer", "Viewer#12345").status_code == 401

    role_change = auth_client.patch("/api/auth/users/viewer", headers=h, json={"role": "ANALYST"})
    assert role_change.status_code == 200
    assert role_change.json()["role"] == "ANALYST"


def test_admin_cannot_demote_or_disable_self(auth_client):
    token = _login(auth_client, *ADMIN).json()["token"]
    h = _headers(token)
    assert auth_client.patch("/api/auth/users/admin", headers=h, json={"role": "VIEWER"}).status_code == 422
    assert (
        auth_client.patch("/api/auth/users/admin", headers=h, json={"is_active": False}).status_code
        == 422
    )


def test_audit_trail_records_security_events(auth_client, db_session):
    token = _login(auth_client, *ADMIN).json()["token"]
    auth_client.post(
        "/api/auth/users",
        headers=_headers(token),
        json={"username": "audited.user", "password": "Strong#12345", "role": "VIEWER"},
    )
    from app.models.audit import AuditLog

    entry = (
        db_session.query(AuditLog)
        .filter_by(action="user.created", entity_id="audited.user")
        .one_or_none()
    )
    assert entry is not None
    assert entry.actor == "admin"
    assert entry.result == "success"
