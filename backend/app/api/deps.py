"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.context import set_actor, set_ip
from app.database.session import get_db  # re-export
from app.models.user import User
from app.services.auth_service import auth_service

__all__ = ["get_db", "get_current_user"]


def get_current_user(
    request: Request, session: Session = Depends(get_db)
) -> User:
    """Authenticate the request via ``Authorization: Bearer <token>``.

    Sets the request-scoped actor context so audit entries attribute the
    action to the caller. Raises 401 for missing/invalid/expired sessions.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    token = header[len("Bearer "):].strip()
    user = auth_service.resolve_token(session, token)
    set_actor(user.username)
    from app.core.hardening import client_ip

    set_ip(client_ip(request))
    request.state.user = user
    return user
