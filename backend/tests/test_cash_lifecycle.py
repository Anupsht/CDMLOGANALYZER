"""Unit tests: universal cash lifecycle state machine (Phase 4).

⚠️ Fixtures are SYNTHETIC (see tests/fixtures/README-SYNTHETIC.md).
The lifecycle engine (app/analysis/hardware.py) is driven here with an
inline universal config — no model code involved.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.analysis.hardware import (
    CONFIDENCE_DIRECT,
    CONFIDENCE_INFERRED,
    HardwareAnalyzer,
    HardwareConfig,
    LS_ACCEPTED,
    LS_COUNTED,
    LS_ESCROW,
    LS_INSERTED,
    LS_CONFIRMED,
    LS_JAMMED,
    LS_STORED,
    LS_TRANSPORTING,
    LS_UNKNOWN,
    LS_UNKNOWN_LOCATION,
    LS_VALIDATED,
)


def ev(code, ts, raw="", line=1, file_id="f1", device=None):
    return SimpleNamespace(
        event_code=code,
        timestamp=ts,
        raw_text=raw,
        line_number=line,
        log_file_id=file_id,
        device=device,
    )


def T(s: str) -> datetime:
    return datetime.strptime(f"2026-07-05 {s}", "%Y-%m-%d %H:%M:%S")


CONFIG = HardwareConfig.from_yaml(
    {
        "sensors": [{"pattern": r"SENS\|(?P<name>\w+)\|(?P<previous>\w+)->(?P<new>\w+)"}],
        "motors": [
            {
                "start_pattern": r"MOTOR\|(?P<name>\w+)\|START",
                "stop_pattern": r"MOTOR\|(?P<name>\w+)\|STOP",
                "timeout_ms": 8000,
            }
        ],
        "transport": {
            "motor_names": ["TRANSPORT"],
            "timeout_ms": 10000,
            "sensors": [{"sensor": "GATE_MAIN", "expected": "OPEN", "blocked": ["CLOSED"]}],
        },
    }
)


def analyze(events):
    return HardwareAnalyzer(CONFIG).analyze(events)


def test_full_chain_states_and_confidences():
    events = [
        ev("CASH_INSERTED", T("10:00:01"), line=1),
        ev("CASH_ACCEPTED", T("10:00:02"), line=2),
        ev("CASH_ESCROWED", T("10:00:03"), line=3),
        ev("CASH_COUNTING_COMPLETED", T("10:00:04"), line=4),
        ev("VALIDATION_PASSED", T("10:00:05"), line=5),
        ev("HOST_RESPONSE", T("10:00:06"), line=6),
        ev("MOTOR_STARTED", T("10:00:07"), raw="MOTOR|TRANSPORT|START", line=7),
        ev("CASH_STORED", T("10:00:09"), line=9),
    ]
    report = analyze(events)
    chain = [(m.from_state, m.to_state, m.confidence) for m in report.movements]
    assert chain == [
        (LS_UNKNOWN, LS_INSERTED, CONFIDENCE_DIRECT),
        (LS_INSERTED, LS_ACCEPTED, CONFIDENCE_DIRECT),
        (LS_ACCEPTED, LS_ESCROW, CONFIDENCE_DIRECT),
        (LS_ESCROW, LS_COUNTED, CONFIDENCE_DIRECT),
        (LS_COUNTED, LS_VALIDATED, CONFIDENCE_DIRECT),
        (LS_VALIDATED, LS_CONFIRMED, CONFIDENCE_DIRECT),
        (LS_CONFIRMED, LS_TRANSPORTING, CONFIDENCE_INFERRED),  # transport motor start
        (LS_TRANSPORTING, LS_STORED, CONFIDENCE_DIRECT),
    ]
    assert report.final_cash_state == LS_STORED


def test_unresolved_flow_is_unknown_location():
    events = [
        ev("CASH_INSERTED", T("10:00:01"), line=1),
        ev("CASH_ACCEPTED", T("10:00:02"), line=2),
        ev("CASH_COUNTING_COMPLETED", T("10:00:03"), line=3),
    ]
    report = analyze(events)
    assert report.final_cash_state == LS_UNKNOWN_LOCATION


def test_jam_without_resolution_is_jammed():
    events = [
        ev("CASH_ACCEPTED", T("10:00:02"), line=1),
        ev("JAM_DETECTED", T("10:00:05"), raw="... |JAM|TRANSPORT ...", line=2),
    ]
    report = analyze(events)
    assert report.final_cash_state == LS_JAMMED


def test_movement_carries_evidence_pointer():
    events = [
        ev("CASH_ACCEPTED", T("10:00:02"), raw="RAW LINE 42", line=42, file_id="file-9"),
    ]
    report = analyze(events)
    m = report.movements[0]
    assert (m.log_file_id, m.line_number, m.raw_text) == ("file-9", 42, "RAW LINE 42")
    assert m.evidence_event == "CASH_ACCEPTED"


def test_lifecycle_overrides_are_config_driven():
    cfg = HardwareConfig.from_yaml(
        {"cash": {"lifecycle_overrides": {"NOTE_RECYCLED": "RETURNED"}}}
    )
    report = HardwareAnalyzer(cfg).analyze([ev("NOTE_RECYCLED", T("10:00:01"), line=1)])
    assert report.movements[0].to_state == "RETURNED"


def test_no_cash_events_yields_unknown():
    report = analyze([ev("TRANSACTION_STARTED", T("10:00:01"), line=1)])
    assert report.movements == []
    assert report.final_cash_state == LS_UNKNOWN


def test_note_info_extracted_only_where_present():
    cfg = HardwareConfig.from_yaml(
        {
            "cash": {
                "notes": [
                    {"key": "denomination", "pattern": r"denom[=:]([0-9]+)", "type": "int"},
                    {"key": "serial", "pattern": r"serial[=:]([A-Za-z0-9]+)", "type": "str"},
                ]
            }
        }
    )
    report = HardwareAnalyzer(cfg).analyze(
        [ev("CASH_ACCEPTED", T("10:00:01"), raw="ESCROW_IN amt=100.00 denom=100", line=1)]
    )
    info = report.movements[0].note_info
    assert info == {"denomination": 100, "serial": "UNKNOWN"}  # missing never invented
