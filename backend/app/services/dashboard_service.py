"""Phase 7 dashboard aggregation service (read-only, model-agnostic).

Every counter is derived from stored evidence (transactions, universal
event codes, Phase-5 diagnostic findings). Nothing here interprets or
invents outcomes; classification was already done by the data-driven
rules engine. No model-code branches exist in this module.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session

from app.models.diagnostics import DiagnosticFinding
from app.models.hardware import SensorEvent
from app.models.machine import Machine
from app.models.transaction import Transaction, TransactionEvent

# Failure classes / rule ids are the standing Phase-5 vocabulary.
_CLASS_HARDWARE = "HARDWARE_FAILURE"
_CLASS_CASH = "CASH_EXCEPTION"
_CLASS_HOST = "HOST_FAILURE"
_RULE_POSSIBLE_JAM = "POSSIBLE_CASH_JAM"
_RULE_CONFIRMED_JAM = "CONFIRMED_CASH_JAM"

# Universal event codes used for machine-health counters.
_EVENT_DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"
_EVENT_JAM_CLEARED = "JAM_CLEARED"


class DashboardService:
    """Aggregates for the technician dashboard and machine health page."""

    # ------------------------------------------------------------------ #
    # Fleet / global summary
    # ------------------------------------------------------------------ #

    def summary(
        self,
        session: Session,
        *,
        machine_id: str | None = None,
        model_code: str | None = None,
        start_from: datetime | None = None,
        start_to: datetime | None = None,
        online_window_hours: int = 24,
    ) -> dict:
        txn_q = session.query(Transaction)
        if machine_id:
            txn_q = txn_q.filter(Transaction.machine_id == machine_id)
        if model_code:
            txn_q = txn_q.filter(Transaction.model_code == model_code.upper())
        if start_from:
            txn_q = txn_q.filter(Transaction.start_time >= start_from)
        if start_to:
            txn_q = txn_q.filter(Transaction.start_time <= start_to)
        txn_subq = txn_q.subquery()

        total = session.query(func.count()).select_from(txn_subq).scalar() or 0
        status_counts = dict(
            session.query(txn_subq.c.status, func.count())
            .select_from(txn_subq)
            .group_by(txn_subq.c.status)
            .all()
        )

        findings = self._finding_counts(
            session, txn_subq=txn_subq
        )

        fleet = self._fleet_status(session, online_window_hours)

        # Per-model breakdown (only models actually present in the window).
        model_rows = (
            session.query(
                txn_subq.c.model_code,
                func.count().label("transactions"),
                func.sum(func.coalesce(txn_subq.c.status == "COMPLETED", 0)).label("completed"),
                func.sum(func.coalesce(txn_subq.c.status == "FAILED", 0)).label("failed"),
                func.sum(func.coalesce(txn_subq.c.status == "DECLINED", 0)).label("declined"),
                func.sum(func.coalesce(txn_subq.c.status == "INCOMPLETE", 0)).label("incomplete"),
            )
            .select_from(txn_subq)
            .group_by(txn_subq.c.model_code)
            .order_by(func.count().desc())
            .all()
        )
        models = [
            {
                "model_code": row.model_code or "UNKNOWN",
                "transactions": int(row.transactions or 0),
                "completed": int(row.completed or 0),
                "failed": int(row.failed or 0),
                "declined": int(row.declined or 0),
                "incomplete": int(row.incomplete or 0),
            }
            for row in model_rows
        ]

        return {
            "generated_at": datetime.now(timezone.utc),
            "window_start": start_from,
            "window_end": start_to,
            "fleet": fleet,
            "transactions": {
                "total": total,
                "completed": int(status_counts.get("COMPLETED", 0)),
                "declined": int(status_counts.get("DECLINED", 0)),
                "failed": int(status_counts.get("FAILED", 0)),
                "incomplete": int(status_counts.get("INCOMPLETE", 0)),
            },
            "findings": findings,
            "models": models,
        }

    def _finding_counts(self, session: Session, *, txn_subq) -> dict:
        """Distinct-transaction finding counters scoped to a txn subquery."""

        def count(query_filter) -> int:
            q = (
                session.query(func.count(func.distinct(DiagnosticFinding.transaction_id)))
                .select_from(DiagnosticFinding)
                .join(txn_subq, txn_subq.c.id == DiagnosticFinding.transaction_id)
            )
            return int(q.filter(query_filter).scalar() or 0)

        return {
            "hardware_errors": count(DiagnosticFinding.diagnosis_class == _CLASS_HARDWARE),
            "possible_jams": count(DiagnosticFinding.rule_id == _RULE_POSSIBLE_JAM),
            "confirmed_jams": count(DiagnosticFinding.rule_id == _RULE_CONFIRMED_JAM),
            "cash_exceptions": count(DiagnosticFinding.diagnosis_class == _CLASS_CASH),
            "host_failures": count(DiagnosticFinding.diagnosis_class == _CLASS_HOST),
        }

    def _fleet_status(self, session: Session, online_window_hours: int) -> dict:
        total = session.query(func.count(Machine.id)).scalar() or 0
        if total == 0:
            return {
                "total": 0,
                "online": 0,
                "offline": 0,
                "window_hours": online_window_hours,
            }
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            hours=online_window_hours
        )
        # A machine counts as online when it logged activity inside the
        # window or an operator explicitly set status='online'.
        active_ids = {
            row[0]
            for row in session.query(Transaction.machine_id)
            .filter(Transaction.machine_id.isnot(None))
            .filter(Transaction.start_time >= cutoff)
            .distinct()
            .all()
        }
        explicit_online = {
            row[0]
            for row in session.query(Machine.id)
            .filter(Machine.status == "online")
            .all()
        }
        online = len(active_ids | explicit_online)
        return {
            "total": int(total),
            "online": online,
            "offline": int(total) - online,
            "window_hours": online_window_hours,
        }

    # ------------------------------------------------------------------ #
    # Per-machine health metrics (raw counters — score is client-side)
    # ------------------------------------------------------------------ #

    def machine_health(
        self, session: Session, machine_id: str, *, window_days: int = 30
    ) -> dict:
        machine = session.query(Machine).filter(Machine.id == machine_id).first()
        if machine is None:
            raise LookupError(f"machine {machine_id} not found")

        window_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=window_days
        )
        base = session.query(Transaction).filter(
            Transaction.machine_id == machine_id,
            or_(Transaction.start_time.is_(None), Transaction.start_time >= window_start),
        )
        txn_subq = base.subquery()

        total = session.query(func.count()).select_from(txn_subq).scalar() or 0
        status_counts = dict(
            session.query(txn_subq.c.status, func.count())
            .select_from(txn_subq)
            .group_by(txn_subq.c.status)
            .all()
        )
        completed = int(status_counts.get("COMPLETED", 0))
        failed = int(status_counts.get("FAILED", 0))
        declined = int(status_counts.get("DECLINED", 0))
        incomplete = int(status_counts.get("INCOMPLETE", 0))
        not_completed = failed + declined + incomplete

        findings = self._finding_counts(session, txn_subq=txn_subq)

        # Sensor abnormalities: mismatch between expected and actual state,
        # or an abnormal duration flagged by the Phase-4 extractor.
        sensor_abnormal = (
            session.query(func.count(SensorEvent.id))
            .join(txn_subq, txn_subq.c.id == SensorEvent.transaction_id)
            .filter(
                or_(
                    SensorEvent.abnormal_duration_ms.isnot(None),
                    and_(
                        SensorEvent.expected_state.isnot(None),
                        SensorEvent.actual_state.isnot(None),
                        SensorEvent.expected_state != SensorEvent.actual_state,
                    ),
                )
            )
            .scalar()
            or 0
        )

        # Device-unavailable / recovery-reset events (universal codes).

        def event_count(*codes: str) -> int:
            return int(
                (
                    session.query(func.count(TransactionEvent.id))
                    .join(txn_subq, txn_subq.c.id == TransactionEvent.transaction_id)
                    .filter(TransactionEvent.event_code.in_(codes))
                ).scalar()
                or 0
            )

        device_unavailable = event_count(_EVENT_DEVICE_UNAVAILABLE)
        recovery_reset = event_count(_EVENT_JAM_CLEARED)
        reset_like = (
            session.query(func.count(TransactionEvent.id))
            .join(txn_subq, txn_subq.c.id == TransactionEvent.transaction_id)
            .filter(TransactionEvent.event_code.ilike("%RESET%"))
            .scalar()
            or 0
        )
        recovery_reset += int(reset_like)

        last_activity = (
            session.query(func.max(Transaction.start_time))
            .filter(Transaction.machine_id == machine_id)
            .scalar()
        )

        model_code = None
        if machine.machine_model is not None:
            model_code = machine.machine_model.code

        return {
            "machine_id": machine.id,
            "serial_number": machine.serial_number,
            "name": machine.name,
            "model_code": model_code,
            "location": machine.location,
            "status": machine.status,
            "window_days": window_days,
            "window_start": window_start,
            "transactions_total": int(total),
            "completed": completed,
            "declined": declined,
            "failed": failed,
            "incomplete": incomplete,
            "failure_rate": round(not_completed / total, 4) if total else 0.0,
            "jam_transactions": findings["possible_jams"] + findings["confirmed_jams"],
            "jam_frequency": round(
                (findings["possible_jams"] + findings["confirmed_jams"]) / total, 4
            )
            if total
            else 0.0,
            "hardware_error_transactions": findings["hardware_errors"],
            "sensor_abnormalities": int(sensor_abnormal),
            "device_unavailable_events": device_unavailable,
            "recovery_reset_events": recovery_reset,
            "last_activity_at": last_activity,
        }


dashboard_service = DashboardService()
