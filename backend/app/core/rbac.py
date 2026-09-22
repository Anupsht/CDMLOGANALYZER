"""Phase 10 — roles and the permission matrix (single source of truth).

Roles: ADMIN, TECHNICIAN, SUPERVISOR, ANALYST, VIEWER (plus the legacy
non-interactive ``service`` account which has no API permissions).

The matrix is explicit per permission — there is no implicit inheritance —
so least privilege is visible at a glance. Frontend mirrors this map for
navigation only; the backend is the enforcement point.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException

from app.api.deps import get_current_user
from app.models.user import User

ROLES = ("ADMIN", "TECHNICIAN", "SUPERVISOR", "ANALYST", "VIEWER")

_ADMIN, _TECH, _SUPER, _ANALYST, _VIEWER = ROLES
_ALL = set(ROLES)

PERMISSIONS: dict[str, set[str]] = {
    # ---- read surfaces (every authenticated role) ------------------------
    "dashboard:read": set(_ALL),
    "logs:read": set(_ALL),
    "transactions:read": set(_ALL),
    "machines:read": set(_ALL),
    "models:read": set(_ALL),
    "cases:read": set(_ALL),
    # ---- technician workflow ---------------------------------------------
    "logs:upload": {_ADMIN, _TECH},
    "analysis:run": {_ADMIN, _TECH, _ANALYST},
    "reports:generate": {_ADMIN, _TECH, _SUPER},
    "cases:create": {_ADMIN, _TECH},
    "cases:update": {_ADMIN, _TECH, _SUPER},
    "machines:write": {_ADMIN, _TECH},
    # ---- analyst / supervisor surfaces ------------------------------------
    "analytics:read": {_ADMIN, _SUPER, _ANALYST},
    "rules:suggest": {_ADMIN, _SUPER, _ANALYST},
    # ---- supervisor --------------------------------------------------------
    "rules:review": {_ADMIN, _SUPER},
    "audit:read": {_ADMIN, _SUPER},
    # ---- admin only ---------------------------------------------------------
    "models:write": {_ADMIN},
    "users:manage": {_ADMIN},
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    role: {perm for perm, roles in PERMISSIONS.items() if role in roles}
    for role in (*ROLES, "SERVICE")
}


def normalize_role(role: str | None) -> str:
    return (role or "VIEWER").strip().upper()


def role_has(role: str | None, permission: str) -> bool:
    """True when ``role`` grants ``permission``. The service account has none."""
    normalized = normalize_role(role)
    if normalized == "SERVICE":
        return False
    return normalized in PERMISSIONS.get(permission, set())


def require_permission(permission: str):
    """FastAPI dependency factory enforcing ``permission`` for the caller."""

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if not role_has(user.role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Role {normalize_role(user.role)} lacks permission '{permission}'.",
            )
        return user

    return _dependency
