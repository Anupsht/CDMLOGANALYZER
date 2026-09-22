"""Unit tests: evidence-based jam classification (Phase 4).

⚠️ Fixtures are SYNTHETIC (see tests/fixtures/README-SYNTHETIC.md).
Classification rules under test (app/analysis/hardware.py):
* CONFIRMED_JAM requires an explicit indication PLUS independent
  corroboration — a single error code never equals a confirmed jam;
* statements report facts + hedged hypotheses, never component failures.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.analysis.hardware import (
    CONFIRMED_JAM,
    HardwareAnalyzer,
    HardwareConfig,
    INSUFFICIENT_DATA,
    NO_EVIDENCE_OF_JAM,
    POSSIBLE_JAM,
    PROBABLE_JAM,
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
        "gates": {
            "command_pattern": r"GATE\|(?P<name>\w+)\|CMD\|(?P<command>[A-Z]+)",
            "position_pattern": r"GATE\|(?P<name>\w+)\|POS\|(?P<state>[A-Z]+)",
            "transition_timeout_ms": 5000,
            "expected_state_map": {"OPEN": "OPEN", "CLOSE": "CLOSED"},
        },
        "transport": {
            "motor_names": ["TRANSPORT"],
            "timeout_ms": 10000,
            "sensors": [{"sensor": "GATE_MAIN", "expected": "OPEN", "blocked": ["CLOSED"]}],
        },
        "jam_indications": {"patterns": [r"JAM\|(?!CLEARED)"], "events": ["JAM_DETECTED"]},
        "temporal_analysis": {
            "before_seconds": 30,
            "after_seconds": 60,
            "per_device": {"TRANSPORT": {"before_seconds": 45, "after_seconds": 90}},
        },
    }
)


def analyze(events):
    report = HardwareAnalyzer(CONFIG).analyze(events)
    assert len(report.faults) == 1  # one assessment per transaction
    return report.faults[0], report


def test_confirmed_jam_requires_indication_plus_corroboration():
    fault, _ = analyze(
        [
            ev("CASH_ACCEPTED", T("10:20:02"), line=1),
            ev("MOTOR_STARTED", T("10:20:04"), raw="MOTOR|TRANSPORT|START", line=2),
            ev("JAM_DETECTED", T("10:20:09"), raw="|APP|ERR|JAM|TRANSPORT", line=3),
            ev("TRANSPORT_TIMEOUT", T("10:20:26"), line=4),
        ]
    )
    assert fault.classification == CONFIRMED_JAM
    assert "confirmed by multiple independent log evidence" in fault.statement
    kinds = {e["kind"] for e in fault.evidence}
    assert "jam_indication" in kinds and "transport_timeout" in kinds
    for e in fault.evidence:
        assert {"timestamp", "file_id", "line_number", "raw_text"} <= set(e)
    # per-device temporal window override applies to the TRANSPORT subject
    assert fault.analysis_window["before_seconds"] == 45
    assert fault.analysis_window["after_seconds"] == 90


def test_single_transport_timeout_without_jam_code_is_probable():
    fault, _ = analyze(
        [
            ev("CASH_ACCEPTED", T("10:10:02"), line=1),
            ev("MOTOR_STARTED", T("10:10:04"), raw="MOTOR|TRANSPORT|START", line=2),
            ev("TRANSPORT_TIMEOUT", T("10:10:20"), line=3),
        ]
    )
    assert fault.classification == PROBABLE_JAM
    assert "expected sensor transition(s) not observed" in fault.statement
    # a probable jam is never worded as confirmed
    assert "confirmed" not in fault.statement.lower().replace("not confirmed", "")


def test_explicit_jam_without_corroboration_is_probable():
    fault, _ = analyze(
        [
            ev("CASH_ACCEPTED", T("10:00:02"), line=1),
            ev("JAM_DETECTED", T("10:00:09"), raw="|APP|ERR|JAM|TRANSPORT", line=2),
        ]
    )
    assert fault.classification == PROBABLE_JAM


def test_motor_timeout_alone_is_possible_jam_with_hedged_wording():
    fault, _ = analyze(
        [
            ev("CASH_ACCEPTED", T("10:15:02"), line=1),
            ev("MOTOR_STARTED", T("10:15:05"), raw="MOTOR|STAKER|START", line=2),
            ev("MOTOR_STOPPED", T("10:15:30"), raw="MOTOR|STAKER|STOP", line=3),
            ev("CASH_STORED", T("10:15:31"), line=4),
        ]
    )
    assert fault.classification == POSSIBLE_JAM
    assert "motor STAKER exceeded its 8000 ms timeout (ran 25000 ms)" in fault.statement
    assert "consistent with a possible transport obstruction" in fault.statement
    # Never an unsupported component conclusion:
    assert "motor is damaged" not in fault.statement
    assert "damaged" not in fault.statement
    # non-transport subject → default window (no per-device override)
    assert fault.analysis_window["before_seconds"] == 30
    assert fault.analysis_window["after_seconds"] == 60


def test_gate_mismatch_is_possible_jam():
    fault, _ = analyze(
        [
            ev("CASH_ACCEPTED", T("10:35:02"), line=1),
            ev("GATE_COMMANDED", T("10:35:04"), raw="GATE|DIVERTER|CMD|OPEN", line=2),
            ev("GATE_POSITION", T("10:35:05"), raw="GATE|DIVERTER|POS|CLOSED", line=3),
            ev("CASH_STORED", T("10:35:06"), line=4),
        ]
    )
    assert fault.classification == POSSIBLE_JAM
    assert "gate DIVERTER position CLOSED did not match commanded OPEN" in fault.statement


def test_normal_completion_is_no_evidence_of_jam():
    fault, _ = analyze(
        [
            ev("CASH_ACCEPTED", T("10:00:02"), line=1),
            ev("MOTOR_STARTED", T("10:00:06"), raw="MOTOR|TRANSPORT|START", line=2),
            ev("SENSOR_CHANGED", T("10:00:07"), raw="SENS|GATE_MAIN|CLOSED->OPEN", line=3),
            ev("MOTOR_STOPPED", T("10:00:08"), raw="MOTOR|TRANSPORT|STOP", line=4),
            ev("CASH_STORED", T("10:00:10"), line=5),
        ]
    )
    assert fault.classification == NO_EVIDENCE_OF_JAM
    assert "terminal state: STORED" in fault.statement


def test_no_relevant_events_is_insufficient_data():
    fault, _ = analyze([ev("TRANSACTION_STARTED", T("10:00:01"), line=1)])
    assert fault.classification == INSUFFICIENT_DATA
    assert "neither confirm nor exclude" in fault.statement


def test_cash_mid_flow_without_anomalies_is_insufficient_data():
    fault, _ = analyze(
        [
            ev("CASH_ACCEPTED", T("10:40:03"), line=1),
            ev("CASH_COUNTING_COMPLETED", T("10:40:04"), line=2),
        ]
    )
    assert fault.classification == INSUFFICIENT_DATA
