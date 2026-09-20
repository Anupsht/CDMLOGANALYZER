"""Transaction persistence + queries (universal, model-independent)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.analysis import events as E
from app.analysis.correlator import TransactionDraft, auto_transaction_id, correlate
from app.analysis.reconstructor import STAGE_SEQUENCE, Reconstructor
from app.core.errors import NotFoundError
from app.core.registry import model_registry
from app.models.transaction import Transaction, TransactionEvent

logger = logging.getLogger(__name__)

_RECONSTRUCTOR = Reconstructor()

_STAGE_OF_EVENT: dict[str, str] = {
    code: stage for stage, codes in STAGE_SEQUENCE for code in codes
}


def _stage_of(event_code: str) -> str | None:
    return _STAGE_OF_EVENT.get(event_code)


class TransactionService:
    # ------------------------------------------------------------------
    # correlation + persistence (called by the pipeline)
    # ------------------------------------------------------------------
    def correlate_and_store(self, session: Session, parent_row, events_by_model: dict[str, list]) -> int:
        """Correlate events per model and persist transactions + events.

        Returns the number of transactions stored. A failure here must
        never fail the upload — callers wrap this in try/except.
        """
        stored = 0
        for model_code, events in sorted(events_by_model.items()):
            adapter = model_registry.get_model(model_code)
            if adapter is None or not model_registry.is_enabled(model_code):
                logger.warning(
                    "Skipping correlation for unknown/disabled model",
                    extra={"model_code": model_code},
                )
                continue
            ccfg = adapter.correlation_config()
            drafts = correlate(events, ccfg)
            for draft in drafts:
                if not any(e.keys.get(ccfg.primary_key) for e in draft.events):
                    draft.transaction_id = auto_transaction_id(ccfg.auto_id_prefix, model_code, draft)
                    draft.method = f"{draft.method}+auto_id"
                self._store_draft(session, parent_row, draft)
                stored += 1
            logger.info(
                "Correlation complete for model",
                extra={
                    "operation": "correlation.run",
                    "model_code": model_code,
                    "events": len(events),
                    "transactions": len(drafts),
                },
            )
        session.commit()
        return stored

    def _store_draft(self, session: Session, parent_row, draft: TransactionDraft) -> Transaction:
        start, end = draft.time_span()
        amount = draft.fields.get("amount")
        currency = draft.fields.get("currency")
        txn = Transaction(
            transaction_id=draft.transaction_id[:64],
            machine_id=parent_row.machine_id,
            machine_model_id=parent_row.machine_model_id,
            model_code=draft.model_code,
            start_time=start,
            end_time=end,
            amount=float(amount) if amount is not None else None,
            currency=currency,
            status=_RECONSTRUCTOR.status(draft.events),
            correlation_confidence=round(draft.confidence, 3),
            correlation_method=draft.method[:128],
            source_file_id=parent_row.id,
        )
        session.add(txn)
        session.flush()
        for seq, event in enumerate(draft.events, start=1):
            session.add(
                TransactionEvent(
                    transaction_id=txn.id,
                    seq=seq,
                    event_code=event.event,
                    stage=_stage_of(event.event),
                    device=event.device,
                    severity=event.severity,
                    timestamp=event.timestamp,
                    source_code=event.source_code,
                    model_code=event.model_code,
                    log_file_id=event.log_file_id,
                    line_number=event.line_number,
                    raw_text=event.raw_text,
                    detail=event.detail or None,
                )
            )
        session.flush()
        return txn

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------
    def get(self, session: Session, txn_id: str) -> Transaction:
        txn = session.get(Transaction, txn_id)
        if txn is None:
            raise NotFoundError(f"Transaction not found: {txn_id}")
        return txn

    def list(
        self,
        session: Session,
        *,
        model_code: str | None = None,
        machine_id: str | None = None,
        status: str | None = None,
        transaction_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        query = session.query(Transaction)
        if model_code:
            query = query.filter(Transaction.model_code == model_code.upper())
        if machine_id:
            query = query.filter(Transaction.machine_id == machine_id)
        if status:
            query = query.filter(Transaction.status == status.upper())
        if transaction_id:
            query = query.filter(Transaction.transaction_id.contains(transaction_id))
        total = query.count()
        return (
            list(query.order_by(Transaction.created_at.desc(), Transaction.transaction_id).offset(offset).limit(limit)),
            total,
        )

    def timeline(self, session: Session, txn_id: str) -> dict:
        """Chronological normalized events + NOT_CONFIRMED stage markers.

        Every real entry carries the raw evidence pointer; markers never
        invent evidence (raw=None, flagged ``not_confirmed``).
        """
        txn = self.get(session, txn_id)
        events = list(txn.events)

        entries: list[dict] = []
        for event in events:
            entries.append(
                {
                    "timestamp": event.timestamp,
                    "event": event.event_code,
                    "stage": event.stage,
                    "device": event.device,
                    "severity": event.severity,
                    "source": event.source_code,
                    "detail": event.detail,
                    "not_confirmed": False,
                    "raw": {
                        "file_id": event.log_file_id,
                        "line_number": event.line_number,
                        "raw_text": event.raw_text,
                    },
                }
            )
        # Chronological order; events without timestamps keep insertion order.
        entries.sort(key=lambda e: (e["timestamp"] is not None, e["timestamp"], e["raw"]["line_number"] or 0))

        # Stage reconstruction: mark stages with no confirming event.
        # Uses the universal STAGE_SEQUENCE view (not the per-event stage
        # tag) so indirectly confirmed stages — e.g. cash_insertion
        # confirmed by CASH_ACCEPTED — are reported correctly.
        stage_status = _RECONSTRUCTOR.stage_views(events)
        confirmed_stages = [v.stage for v in stage_status if v.status == "CONFIRMED"]
        missing = [
            {
                "timestamp": None,
                "event": "NOT_CONFIRMED",
                "stage": view.stage,
                "device": None,
                "severity": "DEBUG",
                "source": None,
                "detail": {"stage": view.stage, "reason": "no confirming event found in correlated logs"},
                "not_confirmed": True,
                "raw": None,
            }
            for view in stage_status
            if view.status != "CONFIRMED"
        ]

        return {
            "transaction": txn,
            "entries": entries,
            "not_confirmed_stages": missing,
            "stages_confirmed": sorted(confirmed_stages),
            "stages_not_confirmed": sorted(v.stage for v in stage_status if v.status != "CONFIRMED"),
            "complete": _RECONSTRUCTOR.is_complete(events),
        }


transaction_service = TransactionService()
