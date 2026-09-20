"""Shared schema primitives."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | list | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


class StatusResponse(BaseModel):
    ok: bool
    message: str | None = None


class ListResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
