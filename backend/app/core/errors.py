"""Centralized API error handling.

Every error leaves the API as a clean, predictable envelope:

```json
{
  "error": {"code": "not_found", "message": "…", "details": {…}},
  "request_id": "…"
}
```

Internal stack traces are never exposed to clients; they are logged
with full detail under the same ``request_id``.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import current_request_id, log_operation, monotonic_ms

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for all expected application errors."""

    status_code: int = 400
    code: str = "app_error"
    message: str = "Application error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_envelope(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details or None,
            },
            "request_id": current_request_id(),
        }


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "The submitted data is invalid."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class DuplicateResourceError(AppError):
    status_code = 409
    code = "duplicate_resource"
    message = "The resource already exists."


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "unsupported_file_type"
    message = "This file type is not supported."


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"
    message = "The file exceeds the maximum allowed size."


class StorageError(AppError):
    status_code = 500
    code = "storage_error"
    message = "The file could not be stored."


class ArchiveError(AppError):
    status_code = 400
    code = "archive_error"
    message = "The archive could not be processed safely."


class ProcessingError(AppError):
    status_code = 500
    code = "processing_error"
    message = "Background processing failed."


def _error_response(status_code: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message, "details": details},
            "request_id": current_request_id(),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        log_operation(
            logging.WARNING,
            operation="http.error",
            message=exc.message,
            error=exc.code,
            status=exc.status_code,
        )
        return _error_response(exc.status_code, exc.code, exc.message, exc.details or None)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(loc) for loc in err.get("loc", []) if loc != "body"),
                "issue": err.get("msg"),
                "type": err.get("type"),
            }
            for err in exc.errors()
        ]
        log_operation(
            logging.WARNING,
            operation="http.error",
            message="Request validation failed",
            error="validation_error",
            status=422,
            details=details,
        )
        return _error_response(422, "validation_error", "The submitted data is invalid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            413: "file_too_large",
            422: "validation_error",
            423: "account_locked",
            429: "rate_limited",
        }.get(exc.status_code, f"http_{exc.status_code}")
        return _error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        log_operation(
            logging.ERROR,
            operation="http.error",
            message="Unhandled exception",
            error=f"{type(exc).__name__}: {exc}",
            method=request.method,
            path=request.url.path,
        )
        logger.exception("Unhandled exception while handling %s %s", request.method, request.url.path)
        return _error_response(500, "internal_error", "An unexpected internal error occurred.")
