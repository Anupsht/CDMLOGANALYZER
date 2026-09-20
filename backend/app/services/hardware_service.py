"""Hardware analysis persistence + queries (universal).

Runs after transaction correlation: derives cash movements, hardware
records and the fault assessment from the stored transaction events and
persists them. A failure here must never break correlation itself.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.analysis.hardware import HardwareReport, analyzer_for
from app.models.hardware import (
    CashMovement,
    FaultAssessment,
    GateEvent,
    MotorEvent,
    SensorEvent,
    TransportEvent,
)
from app.models.transaction import Transaction, TransactionEvent

logger = logging.getLogger(__name__)


class HardwareService:
    # ------------------------------------------------------------------
    # analysis + persistence (called from transaction correlation)
    # ------------------------------------------------------------------
    def analyze_transaction(self, session: Session, txn: Transaction) -> HardwareReport | None:
        """Run the universal hardware analyzer over a stored transaction.

        Returns the report (or None when the model ships no hardware
        configuration). Persisted rows are flushed, not committed — the
        caller owns the transaction boundary.
        """
        analyzer = analyzer_for(txn.model_code or "")
        if analyzer is None:
            return None
        events = (
            session.query(TransactionEvent)
            .filter(TransactionEvent.transaction_id == txn.id)
            .order_by(TransactionEvent.seq)
            .all()
        )
        report = analyzer.analyze(events)
        self._persist(session, txn, report)
        logger.info(
            "Hardware analysis complete",
            extra={
                "operation": "hardware.analyze",
                "transaction_id": txn.transaction_id,
                "model_code": txn.model_code,
                "final_cash_state": report.final_cash_state,
                "classification": report.faults[0].classification if report.faults else None,
            },
        )
        return report

    def _persist(self, session: Session, txn: Transaction, report: HardwareReport) -> None:
        for m in report.movements:
            session.add(
                CashMovement(
                    transaction_id=txn.id,
                    note_id=m.note_id,
                    from_state=m.from_state,
                    to_state=m.to_state,
                    timestamp=m.timestamp,
                    device=m.device,
                    evidence_event=m.evidence_event,
                    confidence=m.confidence,
                    note_info=m.note_info,
                    log_file_id=m.log_file_id,
                    line_number=m.line_number,
                    raw_text=m.raw_text,
                )
            )
        for s in report.sensors:
            session.add(
                SensorEvent(
                    transaction_id=txn.id,
                    sensor=s.sensor,
                    previous_state=s.previous_state,
                    new_state=s.new_state,
                    timestamp=s.timestamp,
                    expected_state=s.expected_state,
                    actual_state=s.actual_state,
                    abnormal_duration_ms=s.abnormal_duration_ms,
                    device=s.device,
                    log_file_id=s.log_file_id,
                    line_number=s.line_number,
                    raw_text=s.raw_text,
                    detail=s.detail,
                )
            )
        for m in report.motors:
            session.add(
                MotorEvent(
                    transaction_id=txn.id,
                    motor=m.motor,
                    started_at=m.started_at,
                    stopped_at=m.stopped_at,
                    duration_ms=m.duration_ms,
                    timeout_ms=m.timeout_ms,
                    timed_out=m.timed_out,
                    transport_name=m.transport_name,
                    sensor_transitions=m.sensor_transitions,
                    device=m.device,
                    log_file_id=m.log_file_id,
                    line_number=m.line_number,
                    raw_text=m.raw_text,
                    stop_line_number=m.stop_line_number,
                    stop_raw_text=m.stop_raw_text,
                )
            )
        for g in report.gates + report.shutters:
            session.add(
                GateEvent(
                    transaction_id=txn.id,
                    kind=g.kind,
                    name=g.name,
                    command=g.command,
                    expected_state=g.expected_state,
                    actual_state=g.actual_state,
                    transition_ms=g.transition_ms,
                    timeout_ms=g.timeout_ms,
                    timed_out=g.timed_out,
                    state_mismatch=g.state_mismatch,
                    device=g.device,
                    log_file_id=g.log_file_id,
                    line_number=g.line_number,
                    raw_text=g.raw_text,
                    position_evidence=g.position_evidence,
                )
            )
        for t in report.transports:
            session.add(
                TransportEvent(
                    transaction_id=txn.id,
                    name=t.name,
                    started_at=t.started_at,
                    ended_at=t.ended_at,
                    outcome=t.outcome,
                    timeout_ms=t.timeout_ms,
                    detail=t.detail,
                    device=t.device,
                    log_file_id=t.log_file_id,
                    line_number=t.line_number,
                    raw_text=t.raw_text,
                )
            )
        for f in report.faults:
            session.add(
                FaultAssessment(
                    transaction_id=txn.id,
                    subject_kind=f.subject_kind,
                    subject_name=f.subject_name,
                    classification=f.classification,
                    statement=f.statement,
                    evidence=f.evidence,
                    analysis_window=f.analysis_window,
                )
            )
        session.flush()

    # ------------------------------------------------------------------
    # queries (API)
    # ------------------------------------------------------------------
    def hardware_payload(self, session: Session, txn: Transaction) -> dict:
        """Everything the hardware-timeline endpoint returns, as dicts."""
        txn_id = txn.id
        cash = (
            session.query(CashMovement)
            .filter(CashMovement.transaction_id == txn_id)
            .order_by(CashMovement.timestamp.asc().nullslast(), CashMovement.created_at)
            .all()
        )
        sensors = (
            session.query(SensorEvent)
            .filter(SensorEvent.transaction_id == txn_id)
            .order_by(SensorEvent.timestamp.asc().nullslast(), SensorEvent.created_at)
            .all()
        )
        motors = (
            session.query(MotorEvent)
            .filter(MotorEvent.transaction_id == txn_id)
            .order_by(MotorEvent.started_at.asc().nullslast(), MotorEvent.created_at)
            .all()
        )
        gates_q = session.query(GateEvent).filter(GateEvent.transaction_id == txn_id)
        gates = gates_q.filter(GateEvent.kind == "gate").all()
        shutters = gates_q.filter(GateEvent.kind == "shutter").all()
        transports = (
            session.query(TransportEvent)
            .filter(TransportEvent.transaction_id == txn_id)
            .order_by(TransportEvent.started_at.asc().nullslast(), TransportEvent.created_at)
            .all()
        )
        faults = (
            session.query(FaultAssessment)
            .filter(FaultAssessment.transaction_id == txn_id)
            .order_by(FaultAssessment.assessed_at)
            .all()
        )

        # Final cash state: same rule as the analyzer — terminal/JAMMED keep
        # their state, anything unresolved becomes UNKNOWN_LOCATION.
        terminal = {"STORED", "REJECTED", "RETURNED"}
        if not cash:
            final_state = "UNKNOWN"
        else:
            last = cash[-1].to_state
            final_state = last if last in terminal or last == "JAMMED" else "UNKNOWN_LOCATION"

        timeline = self._merged_timeline(txn, cash, sensors, motors, gates, shutters, transports, faults)

        return {
            "transaction": txn,
            "final_cash_state": final_state,
            "cash_movements": cash,
            "sensor_events": sensors,
            "motor_events": motors,
            "gate_events": gates,
            "shutter_events": shutters,
            "transport_events": transports,
            "faults": faults,
            "timeline": timeline,
        }

    def _merged_timeline(self, txn, cash, sensors, motors, gates, shutters, transports, faults) -> list[dict]:
        entries: list[dict] = []
        for ev in txn.events:
            entries.append(
                {
                    "timestamp": ev.timestamp,
                    "kind": "transaction",
                    "name": None,
                    "event": ev.event_code,
                    "device": ev.device,
                    "severity": ev.severity,
                    "detail": ev.detail,
                    "raw": {"file_id": ev.log_file_id, "line_number": ev.line_number, "raw_text": ev.raw_text},
                }
            )
        for c in cash:
            entries.append(
                {
                    "timestamp": c.timestamp,
                    "kind": "cash",
                    "name": c.to_state,
                    "event": f"CASH_{c.from_state}_TO_{c.to_state}",
                    "device": c.device,
                    "severity": "WARNING" if c.to_state in ("JAMMED", "REJECTED") else "INFO",
                    "detail": {
                        "from_state": c.from_state,
                        "to_state": c.to_state,
                        "confidence": c.confidence,
                        "evidence_event": c.evidence_event,
                        "note_info": c.note_info,
                    },
                    "raw": {"file_id": c.log_file_id, "line_number": c.line_number, "raw_text": c.raw_text},
                }
            )
        for s in sensors:
            entries.append(
                {
                    "timestamp": s.timestamp,
                    "kind": "sensor",
                    "name": s.sensor,
                    "event": "SENSOR_TRANSITION",
                    "device": s.device,
                    "severity": "WARNING" if (s.abnormal_duration_ms or 0) > 0 else "DEBUG",
                    "detail": {
                        "previous_state": s.previous_state,
                        "new_state": s.new_state,
                        "expected_state": s.expected_state,
                        "actual_state": s.actual_state,
                        "abnormal_duration_ms": s.abnormal_duration_ms,
                    },
                    "raw": {"file_id": s.log_file_id, "line_number": s.line_number, "raw_text": s.raw_text},
                }
            )
        for m in motors:
            entries.append(
                {
                    "timestamp": m.started_at,
                    "kind": "motor",
                    "name": m.motor,
                    "event": "MOTOR_RUN_TIMEOUT" if m.timed_out else "MOTOR_RUN",
                    "device": m.device,
                    "severity": "WARNING" if m.timed_out else "DEBUG",
                    "detail": {
                        "stopped_at": m.stopped_at,
                        "duration_ms": m.duration_ms,
                        "timeout_ms": m.timeout_ms,
                        "timed_out": m.timed_out,
                        "transport_name": m.transport_name,
                        "sensor_transitions": m.sensor_transitions,
                    },
                    "raw": {"file_id": m.log_file_id, "line_number": m.line_number, "raw_text": m.raw_text},
                }
            )
        for g in gates + shutters:
            # Gate/shutter rows don't carry their own timestamp column; use
            # the position evidence timestamp when available so the merged
            # timeline stays chronological.
            pos_ts = None
            if g.position_evidence and g.position_evidence.get("timestamp"):
                try:
                    from datetime import datetime

                    pos_ts = datetime.fromisoformat(g.position_evidence["timestamp"])
                except ValueError:
                    pos_ts = None
            entries.append(
                {
                    "timestamp": pos_ts,
                    "kind": g.kind,
                    "name": g.name,
                    "event": (
                        "STATE_MISMATCH"
                        if g.state_mismatch
                        else "POSITION_TIMEOUT" if g.timed_out
                        else "COMMAND_POSITION_OK"
                    ),
                    "device": g.device,
                    "severity": "WARNING" if (g.state_mismatch or g.timed_out) else "DEBUG",
                    "detail": {
                        "command": g.command,
                        "expected_state": g.expected_state,
                        "actual_state": g.actual_state,
                        "transition_ms": g.transition_ms,
                        "timeout_ms": g.timeout_ms,
                    },
                    "raw": {"file_id": g.log_file_id, "line_number": g.line_number, "raw_text": g.raw_text},
                }
            )
        for t in transports:
            entries.append(
                {
                    "timestamp": t.started_at,
                    "kind": "transport",
                    "name": t.name,
                    "event": f"TRANSPORT_{t.outcome}",
                    "device": t.device,
                    "severity": "INFO" if t.outcome == "COMPLETED" else "WARNING",
                    "detail": {"outcome": t.outcome, "timeout_ms": t.timeout_ms, **(t.detail or {})},
                    "raw": {"file_id": t.log_file_id, "line_number": t.line_number, "raw_text": t.raw_text},
                }
            )
        for f in faults:
            entries.append(
                {
                    "timestamp": None,
                    "kind": "fault",
                    "name": f.subject_name or f.subject_kind,
                    "event": f.classification,
                    "device": None,
                    "severity": (
                        "ERROR"
                        if f.classification == "CONFIRMED_JAM"
                        else "WARNING" if f.classification in ("PROBABLE_JAM", "POSSIBLE_JAM")
                        else "INFO"
                    ),
                    "detail": {"statement": f.statement, "analysis_window": f.analysis_window},
                    "raw": None,
                }
            )
        # Chronological order; entries without a timestamp (fault anchors)
        # stay at the end in insertion order.
        from datetime import datetime

        entries.sort(key=lambda e: (e["timestamp"] is None, e["timestamp"] or datetime.min))
        return entries


hardware_service = HardwareService()
