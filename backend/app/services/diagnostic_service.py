"""Phase 5 diagnostic analysis persistence + queries (universal).

Runs after hardware analysis: builds a :class:`DiagnosisContext` from the
stored Phase 2–4 rows, evaluates the data-driven rules and persists the
findings. Failures here must never break correlation. The API report is
recomputed on read (cheap, deterministic) so rule/config changes and
late-arriving subsequent transactions are reflected immediately.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.analysis.diagnostics import DiagnosisContext, DiagnosticReport, engine_for
from app.models.diagnostics import DiagnosticFinding
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


class DiagnosticService:
    # ------------------------------------------------------------------
    # analysis + persistence
    # ------------------------------------------------------------------
    def analyze_transaction(self, session: Session, txn: Transaction) -> DiagnosticReport:
        """Evaluate rules for one transaction and replace stored findings."""
        engine = engine_for(txn.model_code)
        ctx = self._build_context(session, txn)
        report = engine.evaluate(ctx)
        session.query(DiagnosticFinding).filter(
            DiagnosticFinding.transaction_id == txn.id
        ).delete()
        for f in report.findings:
            session.add(
                DiagnosticFinding(
                    transaction_id=txn.id,
                    finding_id=f.finding_id[:96],
                    rule_id=f.rule_id[:96],
                    diagnosis_class=f.diagnosis_class,
                    category=f.category,
                    severity=f.severity,
                    confidence=f.confidence,
                    summary=f.summary,
                    interpretation=f.interpretation,
                    possible_causes=f.possible_causes,
                    recommended_action=f.recommended_action,
                    evidence=f.evidence,
                    cash_states=f.cash_states,
                )
            )
        session.flush()
        return report

    # ------------------------------------------------------------------
    # API report (always recomputed → reflects rule/config changes)
    # ------------------------------------------------------------------
    def report(self, session: Session, txn: Transaction) -> dict:
        report = self.analyze_transaction(session, txn)
        session.commit()
        return self._report_payload(session, txn, report)

    # ------------------------------------------------------------------
    # context assembly from stored Phase 2–4 rows
    # ------------------------------------------------------------------
    def _build_context(self, session: Session, txn: Transaction) -> DiagnosisContext:
        events = (
            session.query(TransactionEvent)
            .filter(TransactionEvent.transaction_id == txn.id)
            .order_by(TransactionEvent.seq)
            .all()
        )
        cash = (
            session.query(CashMovement)
            .filter(CashMovement.transaction_id == txn.id)
            .order_by(CashMovement.timestamp.asc().nullslast(), CashMovement.created_at)
            .all()
        )
        sensors = (
            session.query(SensorEvent)
            .filter(SensorEvent.transaction_id == txn.id)
            .order_by(SensorEvent.timestamp.asc().nullslast(), SensorEvent.created_at)
            .all()
        )
        motors = (
            session.query(MotorEvent)
            .filter(MotorEvent.transaction_id == txn.id)
            .order_by(MotorEvent.started_at.asc().nullslast(), MotorEvent.created_at)
            .all()
        )
        gates = (
            session.query(GateEvent)
            .filter(GateEvent.transaction_id == txn.id)
            .order_by(GateEvent.created_at)
            .all()
        )
        transports = (
            session.query(TransportEvent)
            .filter(TransportEvent.transaction_id == txn.id)
            .order_by(TransportEvent.started_at.asc().nullslast(), TransportEvent.created_at)
            .all()
        )
        faults = (
            session.query(FaultAssessment)
            .filter(FaultAssessment.transaction_id == txn.id)
            .order_by(FaultAssessment.assessed_at)
            .all()
        )

        terminal = {"STORED", "REJECTED", "RETURNED"}
        if not cash:
            final_state = None
        else:
            last = cash[-1].to_state
            final_state = last if last in terminal or last == "JAMMED" else "UNKNOWN_LOCATION"

        return DiagnosisContext(
            transaction_id=txn.transaction_id,
            model_code=txn.model_code,
            status=txn.status,
            events=events,
            cash_movements=cash,
            final_cash_state=final_state,
            sensors=sensors,
            motors=motors,
            gates=gates,
            transports=transports,
            faults=faults,
            subsequent_events=self._subsequent_events(session, txn),
        )

    def _subsequent_events(self, session: Session, txn: Transaction) -> list:
        """Events of later transactions from the same upload — lets the
        requirement engine observe (automatic) recovery after this txn."""
        later = (
            session.query(Transaction)
            .filter(
                Transaction.source_file_id == txn.source_file_id,
                Transaction.id != txn.id,
                Transaction.start_time.isnot(None),
            )
            .all()
        )
        horizon = txn.end_time or txn.start_time
        later = [
            t
            for t in later
            if horizon is not None and t.start_time is not None and t.start_time > horizon
        ]
        if not later:
            return []
        by_id = {t.id for t in later}
        rows = (
            session.query(TransactionEvent)
            .filter(TransactionEvent.transaction_id.in_(by_id))
            .order_by(TransactionEvent.seq)
            .all()
        )
        return rows

    # ------------------------------------------------------------------
    def _report_payload(self, session: Session, txn: Transaction, report: DiagnosticReport) -> dict:
        findings = (
            session.query(DiagnosticFinding)
            .filter(DiagnosticFinding.transaction_id == txn.id)
            .order_by(DiagnosticFinding.created_at, DiagnosticFinding.finding_id)
            .all()
        )
        return {
            "transaction": txn,
            "summary": report.summary,
            "classification": report.classification,
            "diagnosis_class": report.diagnosis_class,
            "severity": report.severity,
            "confidence": report.confidence,
            "final_cash_state": report.final_cash_state,
            "findings": findings,
        }


diagnostic_service = DiagnosticService()
