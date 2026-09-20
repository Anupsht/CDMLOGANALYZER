"""Machine / machine model schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MachineModelOut(BaseModel):
    """A supported CDM model family (adapter registry + DB state)."""

    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    code: str
    name: str
    vendor: str = "GRG Banking"
    description: str | None = None
    is_active: bool
    is_placeholder: bool = False
    supported: bool = True
    supported_sources: list[str] = []
    parser_code: str | None = None
    analysis_status: str | None = None


class MachineCreate(BaseModel):
    serial_number: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=128)
    machine_model_id: str | None = None
    model_code: str | None = Field(default=None, max_length=32)
    location: str | None = Field(default=None, max_length=255)
    status: str = Field(default="unknown", max_length=32)
    commissioned_at: datetime | None = None


class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    serial_number: str
    name: str | None
    machine_model_id: str | None
    location: str | None
    status: str
    commissioned_at: datetime | None
    extra_metadata: dict | list | None
    created_at: datetime
    updated_at: datetime
    machine_model: MachineModelOut | None = None
