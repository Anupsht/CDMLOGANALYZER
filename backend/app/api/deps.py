"""Shared FastAPI dependencies."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.database.session import get_db  # re-export

__all__ = ["get_db"]
