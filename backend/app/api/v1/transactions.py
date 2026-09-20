"""Transaction endpoints (universal — every model flows through these)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.common import ListResponse
from app.schemas.hardware import HardwareTimelineOut
from app.schemas.transaction import (
    TimelineOut,
    TransactionDetailOut,
    TransactionOut,
)
from app.services.hardware_service import hardware_service
from app.services.transaction_service import transaction_service

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=ListResponse[TransactionOut])
def list_transactions(
    model_code: str | None = Query(default=None, description="e.g. P2600N / P2800N"),
    machine_id: str | None = Query(default=None),
    status: str | None = Query(default=None, description="COMPLETED|DECLINED|FAILED|INCOMPLETE"),
    transaction_id: str | None = Query(default=None, description="substring search"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> ListResponse[TransactionOut]:
    items, total = transaction_service.list(
        session,
        model_code=model_code,
        machine_id=machine_id,
        status=status,
        transaction_id=transaction_id,
        limit=limit,
        offset=offset,
    )
    return ListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{txn_id}", response_model=TransactionDetailOut)
def get_transaction(txn_id: str, session: Session = Depends(get_db)) -> TransactionDetailOut:
    txn = transaction_service.get(session, txn_id)
    out = TransactionDetailOut.model_validate(txn)
    events = list(txn.events)
    from app.analysis.reconstructor import Reconstructor

    reconstructor = Reconstructor()
    out.stages_confirmed = sorted({e.stage for e in events if e.stage})
    out.complete = reconstructor.is_complete(events)
    return out


@router.get("/{txn_id}/timeline", response_model=TimelineOut)
def get_transaction_timeline(txn_id: str, session: Session = Depends(get_db)) -> TimelineOut:
    """Chronologically ordered normalized events with raw evidence links.

    Stages without a confirming event are reported as ``NOT_CONFIRMED``
    entries — never invented.
    """
    return TimelineOut.model_validate(transaction_service.timeline(session, txn_id), from_attributes=True)


@router.get("/{txn_id}/hardware", response_model=HardwareTimelineOut)
def get_transaction_hardware(txn_id: str, session: Session = Depends(get_db)) -> HardwareTimelineOut:
    """Hardware & cash-flow timeline (Phase 4).

    Reconstructs, with raw evidence (file + line + raw text) on every
    derived record:

        Transaction → Cash → Device → Sensor/Motor/Gate → Fault → Final
        Cash State

    Fault classifications are evidence-based (CONFIRMED_JAM requires
    multiple independent log sources); a single error code never equals a
    confirmed jam, and statements never claim component-level root causes.
    """
    txn = transaction_service.get(session, txn_id)
    payload = hardware_service.hardware_payload(session, txn)
    return HardwareTimelineOut.model_validate(payload, from_attributes=True)
