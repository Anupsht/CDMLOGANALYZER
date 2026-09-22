"""Test configuration.

Environment is prepared *before* any app import so settings, engine and
storage all point at an isolated temporary location.
"""

from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="cdm-tests-")

os.environ.setdefault("CDM_ENVIRONMENT", "test")
os.environ.setdefault("CDM_DEBUG", "false")
os.environ.setdefault("CDM_DATABASE_URL", f"sqlite:///{_TMP}/test.sqlite3")
os.environ.setdefault("CDM_STORAGE_DIR", os.path.join(_TMP, "storage"))
os.environ.setdefault("CDM_TASK_EAGER", "true")  # process uploads synchronously
os.environ.setdefault("CDM_REDIS_URL", "")
os.environ.setdefault("CDM_CELERY_BROKER_URL", "")
os.environ.setdefault("CDM_LOG_FORMAT", "console")
os.environ.setdefault("CDM_LOG_LEVEL", "INFO")
# Phase 10: fast hashes + disabled rate limits in the test suite.
os.environ.setdefault("CDM_PASSWORD_HASH_ITERATIONS", "1000")
os.environ.setdefault("CDM_RATE_LIMIT_API_PER_MINUTE", "0")
os.environ.setdefault("CDM_RATE_LIMIT_AUTH_PER_MINUTE", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_database():
    """Give every test a clean database with seeded reference data."""
    from app.database.base import Base
    from app.database.init_db import seed_reference_data
    from app.database.session import database
    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=database.engine)
    Base.metadata.create_all(bind=database.engine)
    seed_reference_data()
    yield
    Base.metadata.drop_all(bind=database.engine)


def _override_get_db():
    from app.database.session import database

    session = database.get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def client():
    """TestClient pre-authenticated as the bootstrap ADMIN.

    Phase 10 made the API authenticated; existing tests exercise business
    behaviour, so the default fixture overrides ``get_current_user`` with
    the seeded admin. Phase-10 security tests use ``auth_client`` (no
    override) to exercise the real login/RBAC paths.
    """
    from app.api.deps import get_current_user, get_db
    from app.database.session import database
    from app.main import app
    from app.models.user import User

    def _fake_admin():
        session = database.get_session()
        try:
            return session.query(User).filter(User.username == "admin").one()
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _fake_admin
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client():
    """TestClient WITHOUT the auth override — real login/RBAC behaviour.

    Bootstrap accounts exist (seeded): admin/Admin#12345, technician/
    Tech#12345, supervisor/Super#12345, analyst/Analyst#12345,
    viewer/Viewer#12345 (test-environment passwords, hashed with 1000
    iterations for speed).
    """
    from app.database.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def db_session():
    """Direct DB session for service-level tests."""
    from app.database.session import database

    session = database.get_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def upload_txt(client):
    """Helper factory: upload a text log and return the JSON response."""

    def _upload(name: str = "test-app.log", content: bytes | None = None, **form):
        data = {"file": (name, content or _DEFAULT_LOG, "text/plain")}
        resp = client.post("/api/logs/upload", files=data, data=form or None)
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _upload


_DEFAULT_LOG = b"""2026-01-05 08:00:01 INFO eCAT application started
2026-01-05 08:00:02 INFO CIM module online
2026-01-05 08:00:03 WARNING note level low
2026-01-05 08:00:04 ERROR dispenser jam detected
2026-01-05 08:00:05 INFO recovery complete
"""
