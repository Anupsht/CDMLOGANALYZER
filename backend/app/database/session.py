"""Database engine / session management.

The engine is created lazily from settings so tests (and tools) can
configure the connection before first use. MySQL is the production
target; SQLite is supported for local development and the test-suite.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Database:
    """Lazily initialized engine + session factory."""

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._session_factory: sessionmaker | None = None

    # ---- engine ---------------------------------------------------------

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            settings = get_settings()
            url = settings.database_url
            kwargs: dict = {"echo": settings.sql_echo, "pool_pre_ping": True, "future": True}
            if url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False}
            else:
                kwargs.update(
                    pool_size=10,
                    max_overflow=20,
                    pool_recycle=1800,
                )
            self._engine = create_engine(url, **kwargs)
            logger.info(
                "Database engine created",
                extra={"operation": "database.engine_created", "dialect": self._engine.dialect.name},
            )
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine, expire_on_commit=False, future=True
            )
        return self._session_factory

    # ---- sessions ---------------------------------------------------------

    def get_session(self) -> Session:
        """Create a new session (caller is responsible for closing)."""
        return self.session_factory()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Transactional scope: commits on success, rolls back on error."""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ---- utilities ---------------------------------------------------------

    def healthcheck(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # pragma: no cover - depends on environment
            logger.warning("Database healthcheck failed", extra={"error": str(exc)})
            return False

    def reset(self) -> None:
        """Dispose engine/session factory (used by tests)."""
        if self._engine is not None:
            self._engine.dispose()
        self._engine = None
        self._session_factory = None


database = Database()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    session = database.get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
