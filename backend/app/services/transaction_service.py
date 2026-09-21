"""Transaction persistence + queries (universal, model-independent)."""

from __future__ import annotations

import logging
from datetime import datetime, time

from sqlalchemy import String, and_, cast, exists, func, or_
from sqlalchemy.orm import Session

from app.analysis import events as E
from app.analysis.correlator import TransactionDraft, auto_transaction_id, correlate
from app.analysis.reconstructor import STAGE_SEQUENCE, Reconstructor
from app.core.errors import NotFoundError, ValidationError
from app.core.registry import model_registry
from app.models.transaction import Transaction, TransactionEvent

logger = logging.getLogger(__name__)

_RECONSTRUCTOR = Reconstructor()

_STAGE_OF_EVENT: dict[str, str] = {
    code: stage for stage, codes in STAGE_SEQUENCE for code in codes
}

# Universal event-code groups used by list filters (query logic only —
# the stored data is never reinterpreted).
_HOST_RESPONSE_CODES = ("HOST_RESPONSE",)
_HOST_DECLINED_CODES = ("HOST_DECLINED",)
_FINAL_CASH_CODES = {
    "STORED": ("CASH_STORED",),
    "RETURNED": ("CASH_RETURNED",),
    "REJECTED": ("CASH_REJECTED",),
    "NOT_STORED": ("CASH_ACCEPTED", "CASH_ESCROWED"),
}


def _stage_of(event_code: str) -> str | None:
    return _STAGE_OF_EVENT.get(event_code)


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        parts = value.strip().split(":")
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(value)
        return hh, mm
    except (ValueError, IndexError):
        raise ValidationError(f"invalid time filter (HH:MM expected): {value}") from None


def _time_of_day():
    """'HH:MM' substring of the stored datetime (SQLite & MySQL layout)."""
    return func.substr(cast(Transaction.start_time, String), 12, 5)


def _has_event(*codes: str):
    return exists().where(
        TransactionEvent.transaction_id == Transaction.id,
        TransactionEvent.event_code.in_(codes),
    )


def _host_result_filter(value: str):
    v = value.strip().lower()
    if v == "declined":
        return _has_event(*_HOST_DECLINED_CODES)
    if v == "approved":
        return and_(_has_event(*_HOST_RESPONSE_CODES), ~_has_event(*_HOST_DECLINED_CODES))
    if v in ("no_response", "no-response", "timeout"):
        return and_(
            _has_event("HOST_REQUEST"),
            ~_has_event(*_HOST_RESPONSE_CODES),
            ~_has_event(*_HOST_DECLINED_CODES),
        )
    raise ValidationError(
        f"invalid host_result filter: {value} (approved|declined|no_response)"
    )


def _cash_state_filter(value: str):
    v = value.strip().upper()
    if v == "NOT_STORED":
        return and_(
            _has_event(*_FINAL_CASH_CODES["NOT_STORED"]),
            ~_has_event(*_FINAL_CASH_CODES["STORED"]),
        )
    if v in _FINAL_CASH_CODES:
        return _has_event(*_FINAL_CASH_CODES[v])
    raise ValidationError(
        f"invalid cash_state filter: {value} (STORED|RETURNED|REJECTED|NOT_STORED)"
    )


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
                txn = self._store_draft(session, parent_row, draft)
                stored += 1
                # Phase 4: hardware / cash-flow analysis per transaction.
                # Failure must never break correlation — logged and skipped.
                try:
                    from app.services.hardware_service import hardware_service

                    hardware_service.analyze_transaction(session, txn)
                except Exception:
                    logger.exception(
                        "Hardware analysis failed (transaction kept)",
                        extra={"operation": "hardware.analyze", "transaction_id": txn.transaction_id},
                    )
                # Phase 5: evidence-driven diagnostic findings.
                try:
                    from app.services.diagnostic_service import diagnostic_service

                    diagnostic_service.analyze_transaction(session, txn)
                except Exception:
                    logger.exception(
                        "Diagnostic analysis failed (transaction kept)",
                        extra={"operation": "diagnostics.analyze", "transaction_id": txn.transaction_id},
                    )
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
        try:
            amount = float(amount) if amount is not None else None
        except (TypeError, ValueError):
            amount = None  # a non-numeric amount is never stored
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
        start_from: datetime | None = None,
        start_to: datetime | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
        currency: str | None = None,
        host_result: str | None = None,
        cash_state: str | None = None,
        event_code: str | None = None,
        device: str | None = None,
        error_code: str | None = None,
        sort: str = "created_at",
        dir: str = "desc",
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
        if start_from:
            query = query.filter(Transaction.start_time >= start_from)
        if start_to:
            query = query.filter(Transaction.start_time <= start_to)
        if time_from:
            hh, mm = _parse_hhmm(time_from)
            query = query.filter(_time_of_day() >= f"{hh:02d}:{mm:02d}")
        if time_to:
            hh, mm = _parse_hhmm(time_to)
            query = query.filter(_time_of_day() <= f"{hh:02d}:{mm:02d}")
        if amount_min is not None:
            query = query.filter(Transaction.amount >= amount_min)
        if amount_max is not None:
            query = query.filter(Transaction.amount <= amount_max)
        if currency:
            query = query.filter(Transaction.currency == currency.upper())
        if host_result:
            query = query.filter(_host_result_filter(host_result))
        if cash_state:
            query = query.filter(_cash_state_filter(cash_state))
        if event_code:
            query = query.filter(_has_event(event_code))
        if device:
            query = query.filter(
                exists().where(
                    TransactionEvent.transaction_id == Transaction.id,
                    TransactionEvent.device == device,
                )
            )
        if error_code:
            # ERROR events carry the mapped catalogue code in detail JSON;
            # the verbatim raw line (original evidence) is searched too.
            query = query.filter(
                exists().where(
                    TransactionEvent.transaction_id == Transaction.id,
                    TransactionEvent.event_code.in_(("ERROR", "VALIDATION_FAILED")),
                    or_(
                        cast(TransactionEvent.detail, String).contains(error_code),
                        TransactionEvent.raw_text.contains(error_code),
                    ),
                )
            )

        sort_column = {
            "created_at": Transaction.created_at,
            "start_time": Transaction.start_time,
            "amount": Transaction.amount,
            "transaction_id": Transaction.transaction_id,
        }.get(sort, Transaction.created_at)
        query = query.order_by(
            sort_column.asc() if dir == "asc" else sort_column.desc(),
            Transaction.transaction_id,
        )
        total = query.count()
        return list(query.offset(offset).limit(limit)), total

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
