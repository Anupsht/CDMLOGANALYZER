"""Phase 10 — authentication & user-management service.

Security properties:
* PBKDF2 password hashing (see ``app.core.security``) — plaintext never stored.
* Generic ``invalid credentials`` errors (no username enumeration).
* Per-account brute-force lockout (``login_max_attempts`` / ``login_lockout_minutes``).
* Opaque server-side sessions with expiry and explicit revocation.
* Every security-relevant event is written to the audit trail with result
  success/failure and the client IP.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import current_ip
from app.core.errors import AppError, ValidationError
from app.core.security import (
    hash_password,
    hash_token,
    new_session_token,
    password_violations,
    verify_password,
)
from app.models.auth_session import AuthSession
from app.models.user import User
from app.services.audit_service import audit_service

logger = logging.getLogger(__name__)


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Invalid credentials."


class LockedOutError(AppError):
    status_code = 423
    code = "account_locked"
    message = "Account temporarily locked after repeated failed logins."


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuthService:
    # ------------------------------------------------------------------
    # login / sessions
    # ------------------------------------------------------------------
    def authenticate(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        user_agent: str | None = None,
    ) -> tuple[User, str, datetime]:
        """Verify credentials and mint a session token.

        Returns ``(user, token, expires_at)`` or raises AuthError/LockedOutError.
        """
        settings = get_settings()
        user = session.query(User).filter(User.username == (username or "").strip()).one_or_none()
        ip = current_ip()

        if user is None or not user.is_active or user.password_hash is None:
            # Same audit + error shape for unknown user / inactive / no password
            # so responses do not leak which usernames exist.
            audit_service.record(
                session,
                action="auth.login_failed",
                entity_type="user",
                entity_id=(username or "")[:64] or None,
                result="failure",
                detail={"reason": "unknown_or_inactive"},
            )
            session.commit()  # audit must survive the failed request
            raise AuthError()

        if user.locked_until is not None and user.locked_until > _utcnow():
            audit_service.record(
                session,
                action="auth.login_failed",
                entity_type="user",
                entity_id=user.username,
                actor=user.username,
                result="failure",
                detail={"reason": "locked"},
            )
            session.commit()  # audit must survive the failed request
            raise LockedOutError()

        if not verify_password(password, user.password_hash):
            user.failed_login_count = (user.failed_login_count or 0) + 1
            detail = {"reason": "bad_password", "failed_count": user.failed_login_count}
            if user.failed_login_count >= settings.login_max_attempts:
                user.locked_until = _utcnow() + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
                detail["locked_for_minutes"] = settings.login_lockout_minutes
                logger.warning(
                    "Account locked after failed logins",
                    extra={"operation": "auth.locked", "username": user.username},
                )
            audit_service.record(
                session,
                action="auth.login_failed",
                entity_type="user",
                entity_id=user.username,
                actor=user.username,
                result="failure",
                detail=detail,
            )
            session.commit()  # audit must survive the failed request
            raise AuthError()

        # success — reset lockout state, mint token
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = _utcnow()
        token, expires_at = self._mint_session(session, user, user_agent=user_agent)
        audit_service.record(
            session,
            action="auth.login",
            entity_type="user",
            entity_id=user.username,
            actor=user.username,
        )
        return user, token, expires_at

    def _mint_session(
        self, session: Session, user: User, *, user_agent: str | None = None
    ) -> tuple[str, datetime]:
        settings = get_settings()
        token = new_session_token()
        expires_at = _utcnow() + timedelta(minutes=settings.session_ttl_minutes)
        session.add(
            AuthSession(
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=expires_at,
                ip=current_ip(),
                user_agent=(user_agent or "")[:255] or None,
            )
        )
        session.flush()
        return token, expires_at

    def resolve_token(self, session: Session, token: str) -> User:
        """Return the active user for a valid, unexpired, unrevoked token."""
        if not token:
            raise AuthError("Not authenticated.")
        row = (
            session.query(AuthSession).filter(AuthSession.token_hash == hash_token(token)).one_or_none()
        )
        if row is None or row.revoked_at is not None or row.expires_at <= _utcnow():
            raise AuthError("Session invalid or expired.")
        user = session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise AuthError("Account is disabled.")
        return user

    def logout(self, session: Session, token: str, *, actor: User) -> None:
        row = (
            session.query(AuthSession).filter(AuthSession.token_hash == hash_token(token)).one_or_none()
        )
        if row is not None and row.revoked_at is None:
            row.revoked_at = _utcnow()
        audit_service.record(
            session,
            action="auth.logout",
            entity_type="user",
            entity_id=actor.username,
            actor=actor.username,
        )

    def _revoke_user_sessions(self, session: Session, user_id: str, *, except_token: str | None = None) -> int:
        query = session.query(AuthSession).filter(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
        )
        keep_hash = hash_token(except_token) if except_token else None
        count = 0
        for row in query.all():
            if keep_hash is not None and row.token_hash == keep_hash:
                continue
            row.revoked_at = _utcnow()
            count += 1
        return count

    # ------------------------------------------------------------------
    # passwords
    # ------------------------------------------------------------------
    def change_password(
        self, session: Session, *, user: User, old_password: str, new_password: str,
        current_token: str | None = None,
    ) -> None:
        if not verify_password(old_password, user.password_hash):
            audit_service.record(
                session,
                action="auth.password_change_failed",
                entity_type="user",
                entity_id=user.username,
                actor=user.username,
                result="failure",
            )
            session.commit()  # audit must survive the failed request
            raise ValidationError("Current password is incorrect.")
        self._set_password(session, user, new_password, current_token=current_token)

    def reset_password(
        self, session: Session, *, target: User, new_password: str, admin: User
    ) -> None:
        self._set_password(session, target, new_password)

    def _set_password(
        self, session: Session, user: User, new_password: str, *, current_token: str | None = None
    ) -> None:
        violations = password_violations(new_password)
        if violations:
            raise ValidationError(f"Password policy: {'; '.join(violations)}.")
        user.password_hash = hash_password(new_password)
        user.failed_login_count = 0
        user.locked_until = None
        # Any other session of this user is invalidated by the change.
        self._revoke_user_sessions(session, user.id, except_token=current_token)
        audit_service.record(
            session,
            action="auth.password_changed",
            entity_type="user",
            entity_id=user.username,
        )

    # ------------------------------------------------------------------
    # user administration (users:manage)
    # ------------------------------------------------------------------
    def create_user(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        role: str,
        full_name: str | None = None,
        email: str | None = None,
        actor: str | None = None,
    ) -> User:
        username = (username or "").strip()
        if not username or len(username) > 64 or not all(
            c.isalnum() or c in "._-@" for c in username
        ):
            raise ValidationError("Username must be 1–64 characters (letters, digits, . _ - @).")
        from app.core.rbac import ROLES, normalize_role

        role = normalize_role(role)
        if role not in ROLES:
            raise ValidationError(f"Role must be one of: {', '.join(ROLES)}.")
        if session.query(User).filter(User.username == username).one_or_none() is not None:
            from app.core.errors import DuplicateResourceError

            raise DuplicateResourceError(f"User already exists: {username}")
        violations = password_violations(password)
        if violations:
            raise ValidationError(f"Password policy: {'; '.join(violations)}.")
        user = User(
            username=username,
            role=role,
            full_name=full_name,
            email=email,
            password_hash=hash_password(password),
            is_active=True,
        )
        session.add(user)
        session.flush()
        audit_service.record(
            session,
            action="user.created",
            entity_type="user",
            entity_id=username,
            actor=actor,
            detail={"role": role},
        )
        return user

    def update_user(
        self,
        session: Session,
        *,
        target: User,
        role: str | None = None,
        is_active: bool | None = None,
        actor: str | None = None,
    ) -> User:
        from app.core.rbac import ROLES, normalize_role

        detail: dict = {}
        if role is not None:
            new_role = normalize_role(role)
            if new_role not in ROLES:
                raise ValidationError(f"Role must be one of: {', '.join(ROLES)}.")
            if target.username == actor and new_role != normalize_role(target.role):
                raise ValidationError("Administrators cannot change their own role.")
            detail["role"] = new_role
            target.role = new_role
        if is_active is not None:
            if target.username == actor and not is_active:
                raise ValidationError("Administrators cannot deactivate their own account.")
            detail["is_active"] = is_active
            target.is_active = is_active
            if not is_active:
                self._revoke_user_sessions(session, target.id)
        session.flush()
        audit_service.record(
            session,
            action="user.updated",
            entity_type="user",
            entity_id=target.username,
            actor=actor,
            detail=detail,
        )
        return target

    # ------------------------------------------------------------------
    # bootstrap
    # ------------------------------------------------------------------
    def ensure_bootstrap_admin(self, session: Session) -> None:
        """Create the initial ADMIN (and demo users in development) if absent."""
        settings = get_settings()
        has_admin = (
            session.query(User).filter(sa_func.upper(User.role) == "ADMIN", User.is_active.is_(True)).first()
            is not None
        )
        if not has_admin:
            admin = User(
                username="admin",
                role="ADMIN",
                full_name="Bootstrap administrator",
                password_hash=hash_password(settings.bootstrap_admin_password),
                is_active=True,
            )
            session.add(admin)
            logger.warning(
                "Bootstrapped initial ADMIN account — change its password immediately",
                extra={"operation": "auth.bootstrap_admin", "username": "admin"},
            )
        if settings.environment in ("development", "test") and (
            session.query(User).filter(User.username == "technician").one_or_none() is None
        ):
            demo = (
                ("technician", "TECHNICIAN", "Tech#12345"),
                ("supervisor", "SUPERVISOR", "Super#12345"),
                ("analyst", "ANALYST", "Analyst#12345"),
                ("viewer", "VIEWER", "Viewer#12345"),
            )
            for username, role, password in demo:
                if session.query(User).filter(User.username == username).one_or_none() is None:
                    session.add(
                        User(
                            username=username,
                            role=role,
                            full_name=f"Demo {role.lower()} account",
                            password_hash=hash_password(password),
                            is_active=True,
                        )
                    )
            logger.info(
                "Seeded demo role accounts (development)",
                extra={"operation": "auth.seed_demo_users"},
            )


auth_service = AuthService()
