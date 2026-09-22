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
from app.models.auth_session import AuthSession
from app.models.case import Case
from app.models.machine import Machine, MachineComponent, MachineModel
from app.models.log_file import LogFile, LogLine, LogSource
from app.models.parser import ParserVersion
from app.models.configuration import ModelConfiguration
from app.models.audit import AuditLog
from app.models.transaction import Transaction, TransactionEvent
from app.models.hardware import (
    CashMovement,
    FaultAssessment,
    GateEvent,
    MotorEvent,
    SensorEvent,
    TransportEvent,
)
from app.models.ai import AIExplanation
from app.models.diagnostics import DiagnosticFinding
from app.models.rule_suggestion import RuleSuggestion

__all__ = [
    "User",
    "AuthSession",
    "Case",
    "Machine",
    "MachineModel",
    "MachineComponent",
    "LogFile",
    "LogLine",
    "LogSource",
    "ParserVersion",
    "ModelConfiguration",
    "AuditLog",
    "Transaction",
    "TransactionEvent",
    "CashMovement",
    "SensorEvent",
    "MotorEvent",
    "GateEvent",
    "TransportEvent",
    "FaultAssessment",
    "DiagnosticFinding",
    "AIExplanation",
]
