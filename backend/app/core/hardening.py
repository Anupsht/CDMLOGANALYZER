"""Phase 10 — HTTP hardening middleware: security headers + rate limiting.

Both middlewares are dependency-free and controlled by settings:

* ``SecurityHeadersMiddleware`` — nosniff / frame-deny / referrer-policy /
  minimal CSP on every response.
* ``RateLimitMiddleware`` — in-memory fixed-window limiter per client IP.
  Suitable for single-process deployments; swap for a Redis-backed limiter
  when scaling horizontally. ``*_PER_MINUTE=0`` disables a bucket.
  (Buckets: strict limit for ``/api/auth/*``, default limit for the API.
  Health/doc endpoints are exempt.)
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.context import current_ip, set_ip

logger = logging.getLogger(__name__)

_SEC_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
)

_EXEMPT_PREFIXES = ("/healthz", "/api/health", "/api/readiness", "/docs", "/redoc", "/openapi.json")


def client_ip(request: Request) -> str:
    settings = get_settings()
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name, value in _SEC_HEADERS:
            response.headers.setdefault(name, value)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-IP limiter with separate auth/API buckets."""

    def __init__(self, app, window_seconds: int = 60, max_keys: int = 10_000) -> None:
        super().__init__(app)
        self._window = window_seconds
        self._max_keys = max_keys
        self._hits: dict[str, list[float]] = {}

    def _allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        window_start = now - self._window
        # Bound memory: drop stale buckets wholesale when the table grows.
        if len(self._hits) > self._max_keys:
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > window_start}
        hits = [t for t in self._hits.get(key, []) if t > window_start]
        if len(hits) >= limit:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True

    @staticmethod
    def _too_many() -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": {"code": "rate_limited", "message": "Too many requests — slow down.", "details": None},
                "request_id": "-",
            },
            headers={"Retry-After": "60"},
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if request.method == "OPTIONS" or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        settings = get_settings()
        ip = client_ip(request)
        set_ip(ip)

        if path.startswith("/api/auth"):
            bucket, limit = "auth", settings.rate_limit_auth_per_minute
        elif path.startswith("/api"):
            bucket, limit = "api", settings.rate_limit_api_per_minute
        else:
            bucket, limit = "other", 0

        if limit > 0 and not self._allow(f"{bucket}:{ip}", limit):
            logger.warning("Rate limit exceeded", extra={"operation": "ratelimit.block", "path": path, "ip": ip})
            return self._too_many()
        return await call_next(request)
