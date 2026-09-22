"""Structured application logging.

Every log record is emitted as JSON (or a compact console line in
development) containing:

* ``timestamp``    — ISO-8601 UTC
* ``level``        — DEBUG/INFO/WARNING/ERROR
* ``service``      — always "cdm-log-analyzer"
* ``operation``    — logical operation name (http_request, upload.process, …)
* ``request_id``   — per-request correlation id (also returned in errors)
* ``error``        — error code/message when applicable
* ``duration_ms``  — operation duration in milliseconds
* plus any additional ``extra`` fields passed by the caller.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from app.core.config import get_settings

SERVICE_NAME = "cdm-log-analyzer"

# Populated by the RequestContextMiddleware for every HTTP request and
# available to background tasks via ``bind_request_id``.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex


def bind_request_id(request_id: str) -> None:
    request_id_ctx.set(request_id)


def current_request_id() -> str:
    return request_id_ctx.get()


# LogRecord attributes that are part of the stdlib record itself.
_BASE_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}


class JsonFormatter(logging.Formatter):
    """Emit structured JSON log lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": SERVICE_NAME,
            "logger": record.name,
            "operation": getattr(record, "operation", None) or record.name,
            "request_id": getattr(record, "request_id", None) or current_request_id(),
            "message": record.getMessage(),
        }

        # Any custom `extra` fields are passed through.
        for key, value in record.__dict__.items():
            if key not in _BASE_ATTRS and key not in payload and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)

        if record.exc_info:
            payload["error"] = payload.get(
                "error", f"{record.exc_info[0].__name__}: {record.exc_info[1]}"
            )
            payload["traceback"] = self.formatException(record.exc_info)
        elif getattr(record, "error", None):
            payload.setdefault("error", str(record.error))

        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human friendly single line format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%H:%M:%S")
        rid = (getattr(record, "request_id", None) or current_request_id())[:8]
        duration = getattr(record, "duration_ms", None)
        suffix = f" duration={duration}ms" if duration is not None else ""
        error = getattr(record, "error", None)
        error_part = f" error={error}" if error else ""
        return (
            f"{ts} {record.levelname:<7} [{rid}] {record.getMessage()}"
            f"{suffix}{error_part}"
        )


def configure_logging() -> None:
    """Configure root logging once, based on settings."""
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format.lower() == "console":
        handler.setFormatter(ConsoleFormatter())
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Uvicorn loggers should propagate into the structured pipeline.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(noisy)
        logger.handlers.clear()
        logger.propagate = True

    logging.getLogger("celery").setLevel("INFO")


def log_operation(
    level: int,
    operation: str,
    message: str,
    *,
    logger: logging.Logger | None = None,
    duration_ms: float | None = None,
    error: str | None = None,
    **fields,
) -> None:
    """Small helper for consistent operation logging."""
    extra = {"operation": operation, **fields}
    if duration_ms is not None:
        extra["duration_ms"] = round(duration_ms, 2)
    if error is not None:
        extra["error"] = error
    (logger or logging.getLogger(__name__)).log(level, message, extra=extra)


def monotonic_ms() -> float:
    return time.monotonic() * 1000
