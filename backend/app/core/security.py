"""Phase 10 — password hashing, password policy and token helpers.

Deliberately standard-library only (no new dependencies):

* Passwords: PBKDF2-HMAC-SHA256 with a per-user random salt and a
  configurable iteration count (``CDM_PASSWORD_HASH_ITERATIONS``).
  Stored in the canonical ``pbkdf2_sha256$<iter>$<salt>$<hash>`` format —
  **plaintext passwords are never stored or logged**.
* Sessions: opaque 256-bit random tokens. Only a SHA-256 hash of the token
  is persisted, so a database leak does not leak usable credentials.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from app.core.config import get_settings

_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16
_HASH_BYTES = 32

_TOKEN_BYTES = 32

_PASSWORD_LABEL = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """Hash ``password`` with PBKDF2-HMAC-SHA256 and a random salt."""
    settings = get_settings()
    iterations = max(int(settings.password_hash_iterations), 1_000)
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        (
            _PASSWORD_LABEL,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time verification of ``password`` against a stored hash."""
    if not stored:
        return False
    try:
        label, iterations_b64, salt_b64, hash_b64 = stored.split("$")
        if label != _PASSWORD_LABEL:
            return False
        iterations = int(iterations_b64)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


_PASSWORD_RULES = (
    (re.compile(r"[A-Z]"), "must contain an uppercase letter"),
    (re.compile(r"[a-z]"), "must contain a lowercase letter"),
    (re.compile(r"[0-9]"), "must contain a digit"),
)


def password_violations(password: str) -> list[str]:
    """Return the list of policy violations for a candidate password."""
    settings = get_settings()
    violations: list[str] = []
    minimum = settings.password_min_length
    if len(password) < minimum:
        violations.append(f"must be at least {minimum} characters long")
    for pattern, message in _PASSWORD_RULES:
        if not pattern.search(password):
            violations.append(message)
    return violations


def new_session_token() -> str:
    """A fresh opaque session token (256 bits of entropy)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Deterministic SHA-256 of a session token — this is what we store."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
