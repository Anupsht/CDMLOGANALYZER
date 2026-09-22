"""Pydantic API schemas (request/response contracts)."""

from app.schemas.common import ErrorDetail, ErrorResponse, ListResponse, StatusResponse
from app.schemas.health import HealthResponse
from app.schemas.log_file import LogFileCreateResult, LogFileOut, LogFileStatusOut, LogLineOut
from app.schemas.machine import (
    MachineCreate,
    MachineOut,
    MachineModelOut,
)
from app.schemas.model import ModelAdapterInfo, ModelToggleResponse

__all__ = [
    "ErrorDetail",
    "ErrorResponse",
    "ListResponse",
    "StatusResponse",
    "HealthResponse",
    "LogFileOut",
    "LogFileCreateResult",
    "LogFileStatusOut",
    "LogLineOut",
    "MachineCreate",
    "MachineOut",

    "MachineModelOut",
    "ModelAdapterInfo",
    "ModelToggleResponse",
]
