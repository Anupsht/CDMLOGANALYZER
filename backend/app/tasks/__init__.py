"""Background task queue (Celery when Redis is configured, inline otherwise)."""

from app.tasks.queue import TaskQueue, get_task_queue

__all__ = ["TaskQueue", "get_task_queue"]
