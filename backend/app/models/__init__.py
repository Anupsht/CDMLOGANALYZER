"""SQLAlchemy ORM models.

Tables (Phase 1):
    users, machine_models, machines, machine_components,
    log_sources, log_files, log_lines,
    parser_versions, model_configurations, audit_logs

Future phases extend this schema (transactions, transaction_events,
cash_movements, faults, sensor_events, motor_events, …) without
changing the Phase 1 tables — log_files / log_lines provide the
evidence backbone those tables will reference.
"""

from app.models.user import User
from app.models.machine import Machine, MachineComponent, MachineModel
from app.models.log_file import LogFile, LogLine, LogSource
from app.models.parser import ParserVersion
from app.models.configuration import ModelConfiguration
from app.models.audit import AuditLog

__all__ = [
    "User",
    "Machine",
    "MachineModel",
    "MachineComponent",
    "LogFile",
    "LogLine",
    "LogSource",
    "ParserVersion",
    "ModelConfiguration",
    "AuditLog",
]
