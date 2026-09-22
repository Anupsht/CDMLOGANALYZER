"""FastAPI application factory — Universal GRG CDM Log Analyzer (Phase 1)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.middleware import RequestContextMiddleware
from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, log_operation

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    log_operation(
        logging.INFO,
        operation="app.startup",
        message=f"{settings.app_name} starting",
        version=__version__,
        environment=settings.environment,
    )
    # 1) Load model adapters into the registry (idempotent).
    from app.core.registry import load_adapters, model_registry
    from app.parsers.registry import load_builtin_parsers

    load_adapters()
    load_builtin_parsers()

    # 2) Ensure schema + reference data (idempotent; Alembic handles upgrades).
    from app.database.init_db import init_database

    init_database()

    # 3) Sync registry enabled/disabled flags with the database.
    from app.database.session import database

    with database.session_scope() as session:
        model_registry.sync_from_database(session)

    log_operation(logging.INFO, operation="app.ready", message="Application ready")
    yield
    log_operation(logging.INFO, operation="app.shutdown", message="Application shutting down")
    from app.tasks.queue import reset_task_queue

    reset_task_queue()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Universal GRG CDM Log Analyzer — Phase 1 foundation: "
            "upload, safe ZIP extraction, raw log storage, parser framework, "
            "model adapter registry."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Middleware (order matters: outermost first)
    # Phase 10: security headers + per-IP rate limiting (settings-driven).
    from app.core.hardening import RateLimitMiddleware, SecurityHeadersMiddleware

    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Centralized error handling
    register_exception_handlers(app)

    # Routers
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/healthz", tags=["health"], include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
