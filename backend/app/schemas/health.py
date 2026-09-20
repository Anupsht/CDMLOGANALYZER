"""Health check schemas."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str  # ok | degraded
    version: str
    environment: str
    database: bool
    queue: str  # celery | inline
