"""Health & readiness endpoints (public — used by monitoring/probes)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.database.session import database
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


class ComponentStatus(BaseModel):
    status: str  # ok | down | not_configured | inline | celery
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: str  # ok | degraded
    version: str
    environment: str
    components: dict[str, ComponentStatus]


def _check_redis() -> ComponentStatus:
    settings = get_settings()
    if not settings.redis_url:
        return ComponentStatus(status="not_configured", detail="no CDM_REDIS_URL — inline queue")
    try:
        import redis  # optional dependency at runtime

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        try:
            client.ping()
        finally:
            client.close()
        return ComponentStatus(status="ok")
    except Exception as exc:
        return ComponentStatus(status="down", detail=str(exc)[:200])


def _check_workers() -> ComponentStatus:
    settings = get_settings()
    if settings.task_eager:
        return ComponentStatus(status="ok", detail="eager (synchronous) task mode")
    if settings.celery_broker_url or settings.redis_url:
        # Broker reachability is the meaningful worker signal we can probe
        # cheaply from the web process; celery inspect ping would add seconds.
        redis_status = _check_redis()
        if redis_status.status == "ok":
            return ComponentStatus(status="ok", detail="celery broker reachable")
        if redis_status.status == "not_configured":
            return ComponentStatus(status="ok", detail="inline queue")
        return ComponentStatus(status="down", detail="celery broker unreachable")
    return ComponentStatus(status="ok", detail="inline queue")


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


@router.get("/readiness", response_model=ReadinessResponse)
def readiness() -> ReadinessResponse:
    """Component probe: database, Redis (when configured), background workers."""
    settings = get_settings()
    db_ok = database.healthcheck()
    components = {
        "database": ComponentStatus(status="ok" if db_ok else "down"),
        "redis": _check_redis(),
        "workers": _check_workers(),
    }
    critical_down = components["database"].status != "ok" or components["redis"].status == "down"
    return ReadinessResponse(
        status="degraded" if critical_down else "ok",
        version=settings.version,
        environment=settings.environment,
        components=components,
    )
