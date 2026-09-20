"""Health & readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.database.session import database
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    db_ok = database.healthcheck()
    queue = "inline"
    if settings.task_eager:
        queue = "eager"
    elif settings.celery_broker_url or settings.redis_url:
        queue = "celery"
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=settings.version,
        environment=settings.environment,
        database=db_ok,
        queue=queue,
    )
