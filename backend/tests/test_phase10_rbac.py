"""Phase 10 — RBAC: the permission matrix enforced over the real API."""

from __future__ import annotations

import pytest

ACCOUNTS = {
    "admin": "Admin#12345",
    "technician": "Tech#12345",
    "supervisor": "Super#12345",
    "analyst": "Analyst#12345",
    "viewer": "Viewer#12345",
}


def _login(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": ACCOUNTS[username]}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture(scope="module")
def _module_tokens():
    """Module-scope cache is impossible across fresh DBs — per-test instead."""
    return {}


# ---- unauthenticated access -------------------------------------------------------


def test_api_requires_authentication(auth_client):
    for path in (
        "/api/transactions",
        "/api/logs",
        "/api/machines",
        "/api/dashboard/summary",
        "/api/analytics/overview",
        "/api/cases",
    ):
        assert auth_client.get(path).status_code == 401, path
    assert auth_client.post("/api/logs/upload").status_code == 401
    # health endpoints stay public for monitoring
    assert auth_client.get("/api/health").status_code == 200
    assert auth_client.get("/api/readiness").status_code == 200


# ---- role matrix -------------------------------------------------------------------


def test_viewer_is_read_only(auth_client):
    h = _login(auth_client, "viewer")
    assert auth_client.get("/api/transactions", headers=h).status_code == 200
    assert auth_client.get("/api/logs", headers=h).status_code == 200
    assert auth_client.get("/api/dashboard/summary", headers=h).status_code == 200
    # writes are forbidden
    assert auth_client.post("/api/logs/upload", headers=h).status_code == 403
    assert (
        auth_client.post("/api/machines", headers=h, json={"serial_number": "X"}).status_code == 403
    )
    assert (
        auth_client.post(
            "/api/cases", headers=h, json={"title": "nope case here"}
        ).status_code
        == 403
    )
    assert auth_client.get("/api/analytics/overview", headers=h).status_code == 403
    assert auth_client.get("/api/audit", headers=h).status_code == 403
    assert auth_client.get("/api/auth/users", headers=h).status_code == 403
    assert (
        auth_client.get(
            "/api/transactions/some-id/report.pdf", headers=h
        ).status_code
        == 403
    )


def test_technician_uploads_and_creates_cases_but_not_review(auth_client):
    h = _login(auth_client, "technician")
    upload = auth_client.post(
        "/api/logs/upload",
        headers=h,
        files={"file": ("t.log", b"2026-01-05 08:00:01 INFO eCAT ok\n", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    case = auth_client.post(
        "/api/cases",
        headers=h,
        json={"title": "Jam investigation", "priority": "HIGH"},
    )
    assert case.status_code == 201, case.text
    # technicians may analyze: an unknown txn id surfaces as 404, proving the
    # permission gate passed (analysis:run) and resolution failed instead.
    assert (
        auth_client.post("/api/transactions/unknown-txn/ai-explanation", headers=h).status_code
        == 404
    )
    assert auth_client.get("/api/analytics/overview", headers=h).status_code == 403
    assert (
        auth_client.patch(
            "/api/analytics/rule-suggestions/whatever", headers=h, json={"status": "APPROVED"}
        ).status_code
        == 403
    )
    assert auth_client.get("/api/auth/users", headers=h).status_code == 403


def test_analyst_reads_analytics_and_suggests_but_cannot_upload(auth_client):
    h = _login(auth_client, "analyst")
    assert auth_client.get("/api/analytics/overview", headers=h).status_code == 200
    assert auth_client.get("/api/analytics/insights", headers=h).status_code == 200
    suggestion = auth_client.post(
        "/api/analytics/rule-suggestions",
        headers=h,
        json={"title": "SUGGESTED_X", "pattern_type": "repeated_error"},
    )
    assert suggestion.status_code == 201, suggestion.text
    assert auth_client.post("/api/logs/upload", headers=h).status_code == 403
    # analyst cannot review (supervisor's job) nor manage users
    assert (
        auth_client.patch(
            f"/api/analytics/rule-suggestions/{suggestion.json()['id']}",
            headers=h,
            json={"status": "APPROVED", "reviewed_by": "analyst"},
        ).status_code
        == 403
    )
    assert auth_client.post(
        "/api/auth/users",
        headers=h,
        json={"username": "x", "password": "Strong#12345", "role": "VIEWER"},
    ).status_code == 403


def test_supervisor_reviews_and_closes_cases(auth_client):
    tech = _login(auth_client, "technician")
    case = auth_client.post(
        "/api/cases", headers=tech, json={"title": "Escalated jam pattern"}
    ).json()
    sup = _login(auth_client, "supervisor")
    reviewed = auth_client.patch(
        f"/api/cases/{case['id']}", headers=sup, json={"status": "CLOSED"}
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "CLOSED"
    assert reviewed.json()["closed_at"] is not None
    assert auth_client.get("/api/audit", headers=sup).status_code == 200
    assert auth_client.post("/api/logs/upload", headers=sup).status_code == 403
    assert auth_client.get("/api/auth/users", headers=sup).status_code == 403
    # supervisor lacks analysis:run → 403 before the unknown id is resolved
    assert (
        auth_client.post("/api/transactions/unknown-txn/ai-explanation", headers=sup).status_code
        == 403
    )


def test_rule_suggestion_review_requires_supervisor(auth_client):
    analyst = _login(auth_client, "analyst")
    sug = auth_client.post(
        "/api/analytics/rule-suggestions",
        headers=analyst,
        json={"title": "SUGGESTED_Y", "pattern_type": "time_pattern"},
    ).json()
    sup = _login(auth_client, "supervisor")
    ok = auth_client.patch(
        f"/api/analytics/rule-suggestions/{sug['id']}",
        headers=sup,
        json={"status": "APPROVED", "reviewed_by": "supervisor"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "APPROVED"


def test_admin_has_full_access(auth_client):
    h = _login(auth_client, "admin")
    assert auth_client.get("/api/auth/users", headers=h).status_code == 200
    assert auth_client.get("/api/audit", headers=h).status_code == 200
    assert auth_client.get("/api/analytics/overview", headers=h).status_code == 200
    models = auth_client.get("/api/models", headers=h).json()
    target = models[0]["code"]  # toggle endpoints address models by code
    off = auth_client.post(f"/api/models/{target}/disable", headers=h)
    assert off.status_code == 200
    on = auth_client.post(f"/api/models/{target}/enable", headers=h)
    assert on.status_code == 200


def test_audit_captures_actor_ip_and_case_lifecycle(auth_client):
    tech = _login(auth_client, "technician")
    case = auth_client.post(
        "/api/cases", headers=tech, json={"title": "Audit trail check"}
    ).json()
    audit = auth_client.get(
        "/api/audit", params={"action": "case.created"}, headers=_login(auth_client, "supervisor")
    )
    assert audit.status_code == 200
    entry = next(e for e in audit.json() if e["entity_id"] == case["id"])
    assert entry["actor"] == "technician"
    assert entry["result"] == "success"
    assert entry["ip"]  # client IP recorded


def test_service_account_has_no_api_permissions(auth_client, db_session):
    from app.core.rbac import role_has

    assert not role_has("service", "logs:read")
    assert not role_has("service", "users:manage")
    assert role_has("ADMIN", "users:manage")
    assert not role_has("TECHNICIAN", "analytics:read")
    assert role_has("SUPERVISOR", "rules:review")
