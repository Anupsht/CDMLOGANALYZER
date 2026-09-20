"""Configurable multi-key transaction correlation.

Given the universal events of one upload batch, group them into
transactions using the model's correlation rules (``model.yaml``):

```yaml
correlation:
  primary_key: txn_id          # exact-key grouping → highest confidence
  auto_id_prefix: P2600N-AUTO  # id given to groups without a raw id
  rules:
    - {name: txn_id_exact,   key: txn_id,     weight: 1.0}
    - {name: session_window, key: session_id, weight: 0.6, window_seconds: 300}
    - {name: journal_seq,    key: journal_seq, weight: 0.5, window_seconds: 600}
```

Algorithm (deliberately conservative):

1. **Exact grouping** — events sharing a non-null ``primary_key`` value
   form a transaction (confidence = that rule's weight, normally 1.0).
2. **Rule attachment** — an ungrouped event joins the *nearest* (in time)
   transaction whose events carry the same value for a secondary rule's
   key, provided the event timestamp is within ``window_seconds`` of that
   nearest event. The transaction's confidence becomes
   ``max(confidence, rule.weight)``.
3. **Orphans** — events that match no rule stay out of every
   transaction; they remain available as raw evidence but are never
   forced into a transaction (no invention).

The engine is generic: keys, weights and windows are data.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.analysis.events import NormalizedEvent


@dataclass
class CorrelationRule:
    name: str
    key: str
    weight: float = 0.5
    window_seconds: int | None = None


@dataclass
class CorrelationConfig:
    primary_key: str = "txn_id"
    auto_id_prefix: str = "AUTO"
    rules: list[CorrelationRule] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "CorrelationConfig":
        config = config or {}
        rules = [
            CorrelationRule(
                name=r.get("name", r["key"]),
                key=r["key"],
                weight=float(r.get("weight", 0.5)),
                window_seconds=r.get("window_seconds"),
            )
            for r in config.get("rules", [])
            if "key" in r
        ]
        return cls(
            primary_key=config.get("primary_key", "txn_id"),
            auto_id_prefix=config.get("auto_id_prefix", "AUTO"),
            rules=rules,
        )


@dataclass
class TransactionDraft:
    """A correlated set of events, pre-persistence."""

    transaction_id: str
    model_code: str
    events: list[NormalizedEvent] = field(default_factory=list)
    confidence: float = 0.0
    method: str = "unspecified"
    fields: dict[str, Any] = field(default_factory=dict)  # amount/currency/…

    def merged_keys(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for event in self.events:
            for key, value in event.keys.items():
                if value is None or value == "":
                    continue
                merged.setdefault(key, value)
        return merged

    def time_span(self) -> tuple[datetime | None, datetime | None]:
        stamps = sorted(e.timestamp for e in self.events if e.timestamp is not None)
        return (stamps[0], stamps[-1]) if stamps else (None, None)


def correlate(events: list[NormalizedEvent], config: CorrelationConfig) -> list[TransactionDraft]:
    """Group events into transaction drafts. Deterministic and stable."""
    primary_rule = next(
        (r for r in config.rules if r.key == config.primary_key),
        CorrelationRule("primary", config.primary_key, 1.0),
    )

    groups: dict[Any, TransactionDraft] = {}
    keyed_events: set[int] = set()

    # ---- 1) exact primary-key grouping -----------------------------------
    for event in events:
        value = event.keys.get(config.primary_key)
        if value is None or value == "":
            continue
        draft = groups.get(value)
        if draft is None:
            draft = TransactionDraft(
                transaction_id=str(value),
                model_code=event.model_code,
                confidence=min(1.0, primary_rule.weight),
                method=primary_rule.name,
            )
            groups[value] = draft
        draft.events.append(event)
        keyed_events.add(id(event))

    drafts = list(groups.values())

    # ---- 2) rule-based attachment for ungrouped events --------------------
    for event in events:
        if id(event) in keyed_events:
            continue
        best: tuple[TransactionDraft, CorrelationRule, float] | None = None
        for rule in config.rules:
            if rule.key == config.primary_key:
                continue
            value = event.keys.get(rule.key)
            if value is None or value == "":
                continue
            for draft in drafts:
                if not _same_key_value(draft, rule.key, value):
                    continue
                distance = _nearest_distance(draft, event.timestamp)
                if distance is None:
                    continue  # cannot verify the window without timestamps
                if rule.window_seconds is not None and distance > timedelta(
                    seconds=rule.window_seconds
                ):
                    continue  # outside the configured window: do not attach
                distance_seconds = distance.total_seconds()
                if best is None or distance_seconds < best[2]:
                    best = (draft, rule, distance_seconds)
        if best is not None:
            draft, rule, _ = best
            draft.events.append(event)
            draft.confidence = max(draft.confidence, min(1.0, rule.weight))
            if rule.weight >= 0.6:
                draft.method = f"{draft.method}+{rule.name}"
            keyed_events.add(id(event))

    # ---- 3) stable ordering + derived fields ------------------------------
    for draft in drafts:
        draft.events.sort(key=_event_sort_key)
        draft.fields.update(draft.merged_keys())

    drafts.sort(key=lambda d: (d.time_span()[0] or datetime.min, d.transaction_id))
    return drafts


def auto_transaction_id(prefix: str, model_code: str, draft: TransactionDraft) -> str:
    """Deterministic id for groups that carry no raw transaction id."""
    material = "|".join(
        f"{e.source_code}:{e.line_number}:{e.raw_text}" for e in draft.events[:5]
    )
    digest = hashlib.sha1(f"{model_code}|{material}".encode()).hexdigest()[:10]
    return f"{prefix}-{digest}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _same_key_value(draft: TransactionDraft, key: str, value: Any) -> bool:
    for event in draft.events:
        if event.keys.get(key) == value:
            return True
    return False


def _nearest_distance(draft: TransactionDraft, timestamp: datetime | None) -> timedelta | None:
    if timestamp is None:
        return None
    distances = [
        abs((event.timestamp - timestamp).total_seconds())
        for event in draft.events
        if event.timestamp is not None
    ]
    return timedelta(seconds=min(distances)) if distances else None


def _event_sort_key(event: NormalizedEvent):
    # Events without timestamps keep file/line order after the timestamped ones.
    ts = event.timestamp or datetime.min
    line = event.line_number if event.line_number is not None else 0
    return (ts, event.log_file_id or "", line)
