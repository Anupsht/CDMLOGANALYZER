"""Transaction reconstruction over the universal stage sequence.

A transaction's lifecycle is described by a *universal* stage sequence.
For each stage the reconstructor looks for confirming events:

    CONFIRMED    — at least one normalized event of the stage exists
    NOT_CONFIRMED — no event found (reported, never invented)

The stage sequence is model-independent because it operates purely on
universal event codes; models reach these codes through their own
mappings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.analysis import events as E

# Universal lifecycle: (stage, confirming event codes)
STAGE_SEQUENCE: tuple[tuple[str, frozenset[str]], ...] = (
    ("start", frozenset({E.TRANSACTION_STARTED})),
    ("cash_insertion", frozenset({E.CASH_INSERTED, E.CASH_ACCEPTED})),
    ("cash_acceptance", frozenset({E.CASH_ACCEPTED})),
    ("counting", frozenset({E.CASH_COUNTING_COMPLETED})),
    ("validation", frozenset({E.VALIDATION_PASSED, E.VALIDATION_FAILED})),
    ("host_request", frozenset({E.HOST_REQUEST})),
    ("host_response", frozenset({E.HOST_RESPONSE, E.HOST_DECLINED})),
    ("storage_or_return", frozenset({E.CASH_STORED, E.CASH_RETURNED, E.CASH_REJECTED})),
    ("final_status", frozenset({E.TRANSACTION_COMPLETED, E.TRANSACTION_FAILED})),
)

# Transaction statuses (universal).
TXN_COMPLETED = "COMPLETED"
TXN_DECLINED = "DECLINED"
TXN_FAILED = "FAILED"
TXN_INCOMPLETE = "INCOMPLETE"

StageStatus = str  # "CONFIRMED" | "NOT_CONFIRMED"


@dataclass
class StageView:
    stage: str
    status: StageStatus
    event: str | None = None
    timestamp: Any = None
    line_number: int | None = None
    log_file_id: str | None = None


class Reconstructor:
    """Builds stage views + final status from correlated events."""

    def stage_views(self, events) -> list[StageView]:
        views: list[StageView] = []
        for stage, codes in STAGE_SEQUENCE:
            confirming = [e for e in events if e.event in codes]
            if confirming:
                first = min(confirming, key=lambda e: (e.timestamp is not None, e.timestamp, e.line_number or 0))
                views.append(
                    StageView(
                        stage=stage,
                        status="CONFIRMED",
                        event=first.event,
                        timestamp=first.timestamp,
                        line_number=first.line_number,
                        log_file_id=first.log_file_id,
                    )
                )
            else:
                views.append(StageView(stage=stage, status="NOT_CONFIRMED"))
        return views

    def status(self, events) -> str:
        codes = {e.event for e in events}
        if E.HOST_DECLINED in codes:
            return TXN_DECLINED
        if E.TRANSACTION_FAILED in codes:
            return TXN_FAILED
        if E.TRANSACTION_COMPLETED in codes:
            return TXN_COMPLETED
        return TXN_INCOMPLETE

    def is_complete(self, events) -> bool:
        return all(
            any(e.event in codes for e in events)
            for _, codes in STAGE_SEQUENCE
        )
