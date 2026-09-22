"""Request-scoped context (actor, client IP) shared with the audit trail.

The auth dependency sets ``actor`` once a request is authenticated; the
request-context middleware sets ``ip`` for every request. Services that
write audit entries read these contextvars so call sites do not have to
pass them explicitly.
"""

from __future__ import annotations

from contextvars import ContextVar

_actor: ContextVar[str | None] = ContextVar("cdm_actor", default=None)
_ip: ContextVar[str | None] = ContextVar("cdm_ip", default=None)


def set_actor(username: str | None) -> None:
    _actor.set(username)


def current_actor() -> str | None:
    return _actor.get()


def set_ip(ip: str | None) -> None:
    _ip.set(ip)


def current_ip() -> str | None:
    return _ip.get()
