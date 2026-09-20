"""Request context middleware: request ids + structured access logging."""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import (
    bind_request_id,
    current_request_id,
    log_operation,
    monotonic_ms,
    new_request_id,
)

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        bind_request_id(request_id)
        request.state.request_id = request_id

        started = monotonic_ms()
        try:
            response = await call_next(request)
        finally:
            duration = monotonic_ms() - started
        # call_next raising is handled by the exception handlers; if we get
        # here a response exists.
        response.headers["X-Request-ID"] = current_request_id()
        log_operation(
            logging.INFO,
            operation="http_request",
            message=f"{request.method} {request.url.path}",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration,
        )
        return response
