"""Clean job-processing abstraction.

* **Celery + Redis** — used when ``CDM_CELERY_BROKER_URL`` / ``CDM_REDIS_URL``
  are configured (the Docker Compose setup). Workers scale independently.
* **Inline queue** — a small thread pool running inside the API process,
  used when Redis is not configured (local development, CI). Requires no
  extra services.
* **Eager mode** — ``CDM_TASK_EAGER=true`` executes jobs synchronously;
  used by the test-suite so uploads are fully processed when the request
  returns.

All modes share the same pipeline implementation
(:func:`app.services.pipeline.run_pipeline`).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TASK_PROCESS_UPLOAD = "cdm.logs.process_upload"


class TaskQueue(ABC):
    name: str = "abstract"

    @abstractmethod
    def enqueue(self, task_name: str, *args) -> str: ...


class CeleryQueue(TaskQueue):
    """Delegates to the Celery broker."""

    name = "celery"

    def __init__(self) -> None:
        from app.tasks.celery_app import celery

        self._celery = celery

    def enqueue(self, task_name: str, *args) -> str:
        result = self._celery.send_task(task_name, args=list(args))
        return result.id


class InlineQueue(TaskQueue):
    """Runs jobs in a process-local thread pool (or synchronously if eager)."""

    name = "inline"

    def __init__(self, eager: bool = False, max_workers: int = 2) -> None:
        self._eager = eager
        self._pool: ThreadPoolExecutor | None = None if eager else ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="cdm-task"
        )

    def enqueue(self, task_name: str, *args) -> str:
        import uuid

        job_id = uuid.uuid4().hex
        if task_name != TASK_PROCESS_UPLOAD:
            raise ValueError(f"Inline queue does not know task: {task_name}")

        if self._eager:
            self._run(job_id, *args)
        else:
            assert self._pool is not None
            self._pool.submit(self._run, job_id, *args)
        return job_id

    @staticmethod
    def _run(job_id: str, file_id: str) -> None:
        from app.core.logging import bind_request_id
        from app.services.pipeline import run_pipeline

        bind_request_id(f"task-{job_id[:12]}")
        try:
            run_pipeline(file_id)
        except Exception:  # the pipeline already records failures; belt & braces
            logger.exception("Inline task crashed", extra={"file_id": file_id})

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False)
            self._pool = None


_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    """Return the configured queue implementation (cached)."""
    global _queue
    if _queue is None:
        settings = get_settings()
        if settings.task_eager:
            _queue = InlineQueue(eager=True)
        elif settings.celery_broker_url or settings.redis_url:
            _queue = CeleryQueue()
        else:
            _queue = InlineQueue(eager=False)
        logger.info("Task queue selected", extra={"operation": "queue.selected", "queue": _queue.name})
    return _queue


def reset_task_queue() -> None:
    """Drop the cached queue (tests / config changes)."""
    global _queue
    if _queue is not None and isinstance(_queue, InlineQueue):
        _queue.shutdown()
    _queue = None
