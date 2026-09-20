"""Unit tests for the universal correlation engine."""

from __future__ import annotations

from datetime import datetime

from app.analysis.correlator import CorrelationConfig, correlate
from app.analysis.events import NormalizedEvent


def _event(ts: str, txn_id=None, session_id=None, host_ref=None, journal_seq=None, source="ecat"):
    keys = {}
    if txn_id is not None:
        keys["txn_id"] = txn_id
    if session_id is not None:
        keys["session_id"] = session_id
    if host_ref is not None:
        keys["host_ref"] = host_ref
    if journal_seq is not None:
        keys["journal_seq"] = journal_seq
    return NormalizedEvent(
        model_code="P2600N",
        source_code=source,
        event="UNMAPPED",
        timestamp=datetime.fromisoformat(ts) if ts else None,
        keys=keys,
    )


def _config() -> CorrelationConfig:
    return CorrelationConfig.from_config(
        {
            "primary_key": "txn_id",
            "auto_id_prefix": "T-AUTO",
            "rules": [
                {"name": "txn_id_exact", "key": "txn_id", "weight": 1.0},
                {"name": "session_window", "key": "session_id", "weight": 0.6, "window_seconds": 300},
                {"name": "host_reference", "key": "host_ref", "weight": 0.7},
            ],
        }
    )


def test_primary_key_groups_with_full_confidence():
    events = [
        _event("2026-07-03 10:00:00", txn_id="T1"),
        _event("2026-07-03 10:00:05", txn_id="T1"),
        _event("2026-07-03 10:00:10", txn_id="T2"),
    ]
    drafts = correlate(events, _config())
    assert len(drafts) == 2
    by_id = {d.transaction_id: d for d in drafts}
    assert len(by_id["T1"].events) == 2
    assert by_id["T1"].confidence == 1.0
    assert by_id["T2"].confidence == 1.0


def test_secondary_rule_attaches_within_window():
    events = [
        _event("2026-07-03 10:00:00", txn_id="T1", session_id="S1"),
        _event("2026-07-03 10:01:00", session_id="S1"),  # 60s later, within 300s
    ]
    drafts = correlate(events, _config())
    assert len(drafts) == 1
    assert len(drafts[0].events) == 2
    assert drafts[0].confidence == 1.0  # primary rule still dominates


def test_secondary_rule_rejects_outside_window():
    events = [
        _event("2026-07-03 10:00:00", txn_id="T1", session_id="S1"),
        _event("2026-07-03 10:20:00", session_id="S1"),  # 20 min later, window 300s
    ]
    drafts = correlate(events, _config())
    assert len(drafts) == 1
    assert len(drafts[0].events) == 1  # far event stayed out


def test_events_without_keys_stay_orphans():
    events = [
        _event("2026-07-03 10:00:00", txn_id="T1"),
        _event("2026-07-03 10:00:01"),  # no keys at all
        _event(None),  # no timestamp either
    ]
    drafts = correlate(events, _config())
    assert len(drafts) == 1
    assert len(drafts[0].events) == 1


def test_host_reference_attaches_by_shared_value():
    events = [
        _event("2026-07-03 10:00:00", txn_id="T1", host_ref="HR-1"),
        _event("2026-07-03 10:00:02", host_ref="HR-1"),  # response without txn id
    ]
    drafts = correlate(events, _config())
    assert len(drafts) == 1
    assert len(drafts[0].events) == 2
    assert "host_reference" in drafts[0].method


def test_same_session_different_windows_do_not_merge():
    events = [
        _event("2026-07-03 10:00:00", txn_id="T1", session_id="S1"),
        _event("2026-07-03 10:02:00", txn_id="T2", session_id="S1"),
        _event("2026-07-03 10:03:00", session_id="S1"),  # closer to T2
    ]
    drafts = correlate(events, _config())
    by_id = {d.transaction_id: d for d in drafts}
    assert len(by_id["T1"].events) == 1
    assert len(by_id["T2"].events) == 2  # attached to the nearest group


def test_events_without_timestamps_never_attach_by_window():
    events = [
        _event("2026-07-03 10:00:00", txn_id="T1", session_id="S1"),
        _event(None, session_id="S1"),  # cannot verify the window
    ]
    drafts = correlate(events, _config())
    assert len(drafts) == 1
    assert len(drafts[0].events) == 1
