"""Phase 10 — authentication & user administration endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.errors import NotFoundError
from app.core.rbac import require_permission
from app.models.user import User
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


# ---- request/response shapes -------------------------------------------------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: str
    username: str
    full_name: str | None = None
    email: str | None = None
    role: str
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class LoginOut(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class PasswordChangeIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    role: str
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)


class UserUpdateIn(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class PasswordResetIn(BaseModel):
    new_password: str = Field(min_length=1, max_length=256)


def _user_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


def _bearer_token(request: Request) -> str:
    return (request.headers.get("Authorization", "") or "").removeprefix("Bearer ").strip()


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, request: Request, session: Session = Depends(get_db)) -> LoginOut:
    """Exchange username + password for a bearer session token.

    Failed attempts are audited with the client IP; repeated failures lock
    the account temporarily (see settings ``login_max_attempts``).
    """
    user, token, expires_at = auth_service.authenticate(
        session,
        username=payload.username,
        password=payload.password,
        user_agent=request.headers.get("User-Agent"),
    )
    return LoginOut(token=token, expires_at=expires_at, user=_user_out(user))


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Revoke the presented session token."""
    auth_service.logout(session, _bearer_token(request), actor=user)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


@router.post("/change-password", status_code=204)
def change_password(
    payload: PasswordChangeIn,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Change own password (policy-enforced); other sessions are revoked."""
    auth_service.change_password(
        session,
        user=user,
        old_password=payload.old_password,
        new_password=payload.new_password,
        current_token=_bearer_token(request) or None,
    )
    return Response(status_code=204)


@router.get("/users", response_model=list[UserOut])
def list_users(
    session: Session = Depends(get_db),
    _: User = Depends(require_permission("users:manage")),
) -> list[UserOut]:
    return [_user_out(u) for u in session.query(User).order_by(User.username).all()]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreateIn,
    session: Session = Depends(get_db),
    admin: User = Depends(require_permission("users:manage")),
) -> UserOut:
    user = auth_service.create_user(
        session,
        username=payload.username,
        password=payload.password,
        role=payload.role,
        full_name=payload.full_name,
        email=payload.email,
        actor=admin.username,
    )
    return _user_out(user)


def _target(session: Session, user_id: str) -> User:
    user = session.get(User, user_id)
    if user is None:
        user = session.query(User).filter(User.username == user_id).one_or_none()
    if user is None:
        raise NotFoundError(f"User not found: {user_id}")
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdateIn,
    session: Session = Depends(get_db),
    admin: User = Depends(require_permission("users:manage")),
) -> UserOut:
    target = _target(session, user_id)
    auth_service.update_user(
        session,
        target=target,
        role=payload.role,
        is_active=payload.is_active,
        actor=admin.username,
    )
    return _user_out(target)


@router.post("/users/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: str,
    payload: PasswordResetIn,
    session: Session = Depends(get_db),
    admin: User = Depends(require_permission("users:manage")),
) -> Response:
    """Admin-initiated password reset (policy-enforced; revokes sessions)."""
    target = _target(session, user_id)
    auth_service.reset_password(
        session, target=target, new_password=payload.new_password, admin=admin
    )
    return Response(status_code=204)
