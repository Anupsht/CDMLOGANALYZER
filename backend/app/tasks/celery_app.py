"""Celery application (used only when Redis is configured)."""

from __future__ import annotations

import logging

from celery import Celery

from app.core.config import get_settings
from app.core.logging import bind_request_id

logger = logging.getLogger(__name__)

settings = get_settings()

celery = Celery(
    "cdm_log_analyzer",
    broker=settings.celery_broker_url or settings.redis_url or "redis://localhost:6379/0",
    backend=settings.celery_result_backend or None,
    include=["app.tasks.processing"],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)


@celery.task(name="cdm.logs.process_upload", bind=True, max_retries=3, default_retry_delay=5)
def process_upload(self, file_id: str) -> dict:  # noqa: ANN001
    """Run the Phase 1 processing pipeline for one uploaded file."""
    from app.services.pipeline import run_pipeline

    bind_request_id(f"celery-{self.request.id}")
    logger.info("Celery task received", extra={"operation": "celery.receive", "file_id": file_id})
    return run_pipeline(file_id)
