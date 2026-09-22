"""Machine model registry schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ModelAdapterInfo(BaseModel):
    code: str
    display_name: str
    vendor: str = "GRG Banking"
    description: str | None = None
    enabled: bool
    placeholder: bool = False
    supported_sources: list[str] = []
    parser_code: str | None = None
    analysis_status: str = "pending"  # Phase 2 delivers real analysis


class ModelToggleResponse(BaseModel):
    model_code: str
    enabled: bool
