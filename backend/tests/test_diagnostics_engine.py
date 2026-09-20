"""Phase 5 golden cases: evidence-driven diagnostic engine.

⚠️ SYNTHETIC scenarios (see tests/fixtures/README-SYNTHETIC.md). The
engine runs against the REAL universal rules file
(config/diagnostics/rules.yaml) + the model overlay — the same data the
API serves. Required golden matrix:

successful deposit, host decline, cash exception, confirmed jam,
possible jam, sensor issue, automatic recovery, transaction mismatch.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace as NS

from app.analysis.diagnostics import DiagnosisContext, engine_for

P2600 = engine_for("P2600N")
P2800 = engine_for("P2800N")


# ---------------------------------------------------------------------------
# builders (attribute names mirror the ORM rows)
# ---------------------------------------------------------------------------


def ev(code, ts, raw="", line=1, device="APP", detail=None, file_id="f1"):
    return NS(
        event_code=code, timestamp=ts, raw_text=raw, line_number=line,
        log_file_id=file_id, device=device, detail=detail,
    )


def cash(states, t0, raw="RAW", line=1, file_id="f1"):
    out = []
    prev = "UNKNOWN"
    for i, state in enumerate(states):
        out.append(
            NS(
                from_state=prev, to_state=state, timestamp=t0.replace(minute=t0.minute + i),
                device="APP", evidence_event="E", confidence=1.0, note_info=None,
                log_file_id=file_id, line_number=line, raw_text=raw,
            )
        )
        prev = state
    return out


def T(s):
    return datetime.strptime(f"2026-07-05 {s}", "%Y-%m-%d %H:%M:%S")


def run(engine, events, *, movements=None, status="COMPLETED", sensors=None,
        motors=None, gates=None, transports=None, faults=None,
        final=None, subsequent=None):
    movements = movements if movements is not None else cash(["STORED"], T("10:00:05"))
    if final is None:
        final = movements[-1].to_state if movements else None
    return engine.evaluate(
        DiagnosisContext(
            transaction_id="T", model_code="P2800N", status=status,
            events=events, cash_movements=movements, final_cash_state=final,
            sensors=sensors or [], motors=motors or [], gates=gates or [],
            transports=transports or [], faults=faults or [],
            subsequent_events=subsequent or [],
        )
    )


def ids(report):
    return [f.finding_id for f in report.findings]


# ---------------------------------------------------------------------------
# 1. successful deposit
# ---------------------------------------------------------------------------


def test_golden_successful_deposit():
    report = run(
        P2600,
        [
            ev("TRANSACTION_STARTED", T("10:00:01"), "TRANSACTION_START TXN=T", line=2),
            ev("CASH_INSERTED", T("10:00:02"), "CASH_INSERTED TXN=T AMOUNT=500.00 CURRENCY=CNY NOTES=5", line=3),
            ev("CASH_ACCEPTED", T("10:00:02"), "escrow in, notes accepted TXN=T", line=4),
            ev("CASH_COUNTING_COMPLETED", T("10:00:03"), "COUNTING_COMPLETED TXN=T AMOUNT=500.00 NOTES=5", line=5),
            ev("VALIDATION_PASSED", T("10:00:04"), "VALIDATION_PASSED TXN=T", line=6),
            ev("HOST_REQUEST", T("10:00:05"), "HOST_REQUEST TXN=T", line=7),
            ev("HOST_RESPONSE", T("10:00:06"), "HOST_RESPONSE RESULT=APPROVED TXN=T", line=8),
            ev("MOTOR_STARTED", T("10:00:07"), "motor 1 start TXN=T", line=9),
            ev("SENSOR_CHANGED", T("10:00:08"), "sensor S12 changed 0->1 TXN=T", line=10),
            ev("MOTOR_STOPPED", T("10:00:09"), "motor 1 stop TXN=T", line=11),
            ev("CASH_STORED", T("10:00:10"), "note to stacker TXN=T", line=12),
            ev("TRANSACTION_COMPLETED", T("10:00:11"), "TRANSACTION_END STATUS=SUCCESS", line=13),
        ],
        movements=cash(
            ["INSERTED", "ACCEPTED", "COUNTED", "VALIDATED", "CONFIRMED", "TRANSPORTING", "STORED"],
            T("10:00:02"),
        ),
        status="COMPLETED",
        final="STORED",
    )
    assert "NORMAL_COMPLETION" in ids(report)
    assert report.classification == "NORMAL_COMPLETION"
    assert report.diagnosis_class == "NO_FAILURE"
    assert report.severity == "INFO"
    assert report.confidence == "HIGH"
    assert not [f for f in report.findings if f.diagnosis_class not in ("NO_FAILURE",)]


# ---------------------------------------------------------------------------
# 2. host decline (section 7: HOST_TRANSACTION_FAILURE, not hardware)
# ---------------------------------------------------------------------------


def test_golden_host_decline_is_host_not_hardware():
    report = run(
        P2800,
        [
            ev("TRANSACTION_STARTED", T("10:33:01"), line=1),
            ev("CASH_INSERTED", T("10:33:02"), "CASH_INSERTED TXN=T AMOUNT=300.00 NOTES=6", line=2),
            ev("CASH_ACCEPTED", T("10:33:03"), line=3),
            ev("CASH_COUNTING_COMPLETED", T("10:33:04"), "COUNTING_COMPLETED TXN=T AMOUNT=300.00 NOTES=6", line=4),
            ev("HOST_REQUEST", T("10:33:06"), line=5),
            ev("HOST_DECLINED", T("10:33:09"), "HOST_RESPONSE RESULT=DECLINED TXN=T", line=6),
            ev("CASH_RETURNED", T("10:33:09"), "notes presented to customer TXN=T", line=7),
            ev("TRANSACTION_COMPLETED", T("10:33:10"), "TRANSACTION_END STATUS=DECLINED", line=8),
        ],
        movements=cash(["INSERTED", "ACCEPTED", "COUNTED", "RETURNED"], T("10:33:02")),
        status="DECLINED",
        final="RETURNED",
    )
    finding = next(f for f in report.findings if f.rule_id == "HOST_TRANSACTION_FAILURE")
    assert finding.category == "HOST"
    assert finding.diagnosis_class == "HOST_FAILURE"
    # hardware categories/classes must NOT appear
    assert not [f for f in report.findings if f.diagnosis_class == "HARDWARE_FAILURE"]
    assert report.classification == "HOST_TRANSACTION_FAILURE"
    # every possible cause is host-side, wording never claims hardware faults
    assert "hardware" not in finding.summary.lower()


# ---------------------------------------------------------------------------
# 3. cash exception (accepted, counted, nothing terminal)
# ---------------------------------------------------------------------------


def test_golden_cash_exception_accepted_not_stored():
    report = run(
        P2800,
        [
            ev("TRANSACTION_STARTED", T("10:10:01"), line=1),
            ev("CASH_ACCEPTED", T("10:10:02"), "ESCROW_IN amt=80.00", line=2),
            ev("CASH_COUNTING_COMPLETED", T("10:10:03"), "NOTES_COUNTED amt=80.00", line=3),
            ev("TRANSPORT_STARTED", T("10:10:04"), "MOTOR|TRANSPORT|START", line=4),
            ev("TRANSPORT_TIMEOUT", T("10:10:20"), line=5),
            ev("TRANSACTION_FAILED", T("10:10:21"), "TRX|CLOSE|FAIL", line=6),
        ],
        movements=cash(["ACCEPTED", "COUNTED", "TRANSPORTING"], T("10:10:02")),
        status="FAILED",
        final="UNKNOWN_LOCATION",
    )
    assert "CASH_ACCEPTED_NOT_STORED" in ids(report)
    stored = next(f for f in report.findings if f.rule_id == "CASH_ACCEPTED_NOT_STORED")
    assert stored.category == "CASH_HANDLING"
    assert stored.diagnosis_class == "CASH_EXCEPTION"
    assert stored.severity == "HIGH"
    assert stored.evidence, "cash exception finding must carry evidence"
    assert all({"file_id", "line_number", "raw_text"} <= set(e) for e in stored.evidence)
    assert report.diagnosis_class in ("CASH_EXCEPTION", "HARDWARE_FAILURE")


# ---------------------------------------------------------------------------
# 4. confirmed jam
# ---------------------------------------------------------------------------


def test_golden_confirmed_jam():
    fault = NS(classification="CONFIRMED_JAM", subject_kind="transport", subject_name="TRANSPORT",
               statement="Jam confirmed by multiple independent log evidence.")
    report = run(
        P2800,
        [
            ev("CASH_ACCEPTED", T("10:20:02"), line=1),
            ev("TRANSPORT_STARTED", T("10:20:04"), "MOTOR|TRANSPORT|START", line=2),
            ev("JAM_DETECTED", T("10:20:09"), "|APP|ERR|JAM|TRANSPORT", line=3),
            ev("TRANSPORT_TIMEOUT", T("10:20:26"), line=4),
            ev("TRANSACTION_FAILED", T("10:20:27"), line=5),
        ],
        movements=cash(["ACCEPTED", "COUNTED", "TRANSPORTING", "JAMMED"], T("10:20:02")),
        status="FAILED",
        final="JAMMED",
        faults=[fault],
    )
    jam = next(f for f in report.findings if f.rule_id == "CONFIRMED_CASH_JAM")
    assert jam.category == "TRANSPORT"
    assert jam.diagnosis_class == "HARDWARE_FAILURE"
    assert jam.severity == "CRITICAL"
    assert jam.confidence == "VERY_HIGH"
    assert jam.evidence and jam.evidence[0]["classification"] == "CONFIRMED_JAM"
    assert "component-level root cause" in jam.interpretation
    assert report.classification == "CONFIRMED_CASH_JAM"


# ---------------------------------------------------------------------------
# 5. possible jam — the section-6 diagnostic example
# ---------------------------------------------------------------------------


def test_golden_possible_jam_section6_example():
    sensor = NS(sensor="GATE_MAIN", previous_state="OPEN", new_state="CLOSED",
                expected_state="OPEN", actual_state="CLOSED", abnormal_duration_ms=None,
                timestamp=T("10:00:08"), device="APP", log_file_id="f1", line_number=8,
                raw_text="SENS|GATE_MAIN|OPEN->CLOSED")
    transport = NS(name="TRANSPORT", started_at=T("10:00:06"), ended_at=None,
                   outcome="TIMEOUT", timeout_ms=10000, detail={}, device="APP",
                   log_file_id="f1", line_number=6, raw_text="MOTOR|TRANSPORT|START")
    report = run(
        P2800,
        [
            ev("CASH_ACCEPTED", T("10:00:02"), "ESCROW_IN amt=100.00", line=2),
            ev("TRANSPORT_STARTED", T("10:00:06"), "MOTOR|TRANSPORT|START", line=6),
            ev("SENSOR_CHANGED", T("10:00:08"), "SENS|GATE_MAIN|OPEN->CLOSED", line=8),
            ev("TRANSPORT_TIMEOUT", T("10:00:26"), "TRANSPORT|TIMEOUT", line=26),
        ],
        movements=cash(["ACCEPTED", "TRANSPORTING"], T("10:00:02")),
        status="FAILED",
        final="UNKNOWN_LOCATION",
        sensors=[sensor],
        transports=[transport],
    )
    finding = next(f for f in report.findings if f.rule_id == "TRANSPORT_OBSTRUCTION_SUSPECTED")
    assert finding.summary == "Possible transport obstruction"
    assert finding.severity == "HIGH"
    assert finding.confidence == "HIGH"
    assert finding.possible_causes == ["note obstruction", "sensor issue", "transport timing problem"]
    kinds = {e["kind"] for e in finding.evidence}
    assert {"event", "sensor", "transport"} <= kinds  # evidence: the actual events
    ev_codes = [e.get("event") for e in finding.evidence if e["kind"] == "event"]
    assert {"CASH_ACCEPTED", "TRANSPORT_STARTED", "TRANSPORT_TIMEOUT"} <= set(ev_codes)
    # hedged: consistent-with wording, never certainty
    assert "consistent with" in finding.interpretation


# ---------------------------------------------------------------------------
# 6. sensor issue
# ---------------------------------------------------------------------------


def test_golden_sensor_issue():
    sensor = NS(sensor="S12", previous_state="0", new_state="0",
                expected_state="1", actual_state="0", abnormal_duration_ms=None,
                timestamp=T("10:15:05"), device="CIM", log_file_id="f2", line_number=5,
                raw_text="sensor S12 changed 0->0")
    report = run(
        P2600,
        [
            ev("CASH_ACCEPTED", T("10:15:02"), line=1),
            ev("SENSOR_CHANGED", T("10:15:05"), "sensor S12 changed 0->0 TXN=T", line=2),
            ev("CASH_STORED", T("10:15:10"), line=3),
            ev("TRANSACTION_COMPLETED", T("10:15:11"), line=4),
        ],
        movements=cash(["ACCEPTED", "STORED"], T("10:15:02")),
        status="COMPLETED",
        final="STORED",
        sensors=[sensor],
    )
    finding = next(f for f in report.findings if f.rule_id == "SENSOR_ANOMALY")
    assert finding.category == "SENSOR"
    assert finding.severity == "MEDIUM"
    assert finding.confidence == "LOW"  # a lone anomaly stays low-confidence
    assert "not evidence of a jam" in finding.interpretation
    # NORMAL_COMPLETION must be suppressed by the anomaly
    assert "NORMAL_COMPLETION" not in ids(report)


# ---------------------------------------------------------------------------
# 7. automatic recovery (section 9 requirement violation)
# ---------------------------------------------------------------------------


def test_golden_automatic_recovery_requirement_violation():
    fault = NS(classification="CONFIRMED_JAM", subject_kind="transport", subject_name="TRANSPORT",
               statement="Jam confirmed.")
    report = run(
        P2800,
        [
            ev("CASH_ACCEPTED", T("10:20:02"), line=1),
            ev("TRANSPORT_STARTED", T("10:20:04"), line=2),
            ev("JAM_DETECTED", T("10:20:09"), "|APP|ERR|JAM|TRANSPORT", line=3),
            ev("TRANSPORT_TIMEOUT", T("10:20:26"), line=4),
        ],
        movements=cash(["ACCEPTED", "JAMMED"], T("10:20:02")),
        status="FAILED",
        final="JAMMED",
        faults=[fault],
        # the NEXT transaction on the machine, 90 s later: automatic recovery
        subsequent=[ev("TRANSACTION_STARTED", T("10:21:36"), line=1, file_id="f9")],
    )
    violation = next(f for f in report.findings if f.diagnosis_class == "REQUIREMENT_VIOLATION")
    assert violation.finding_id == "JAM_REQUIRES_MANUAL_OFFLINE"
    assert violation.severity == "HIGH"
    assert "Configured requirement" in violation.interpretation
    kinds = {e["kind"] for e in violation.evidence}
    assert "fault" in kinds and "event" in kinds
    assert any(e.get("event") == "TRANSACTION_STARTED" for e in violation.evidence)


def test_golden_no_requirement_violation_when_machine_stays_down():
    fault = NS(classification="CONFIRMED_JAM", subject_kind="transport", subject_name="TRANSPORT",
               statement="Jam confirmed.")
    report = run(
        P2800,
        [
            ev("CASH_ACCEPTED", T("10:20:02"), line=1),
            ev("JAM_DETECTED", T("10:20:09"), "|APP|ERR|JAM|TRANSPORT", line=2),
        ],
        movements=cash(["ACCEPTED", "JAMMED"], T("10:20:02")),
        status="FAILED",
        final="JAMMED",
        faults=[fault],
        subsequent=[ev("DEVICE_UNAVAILABLE", T("10:21:36"), line=9)],  # offline, as required
    )
    assert not [f for f in report.findings if f.diagnosis_class == "REQUIREMENT_VIOLATION"]


# ---------------------------------------------------------------------------
# 8. transaction mismatch (application failure)
# ---------------------------------------------------------------------------


def test_golden_transaction_mismatch():
    report = run(
        P2800,
        [
            ev("CASH_ACCEPTED", T("10:40:03"), line=1),
            ev("CASH_COUNTING_COMPLETED", T("10:40:04"), line=2),
            ev("TRANSACTION_COMPLETED", T("10:40:05"), "TRX|CLOSE|OK", line=3),
        ],
        movements=cash(["ACCEPTED", "COUNTED"], T("10:40:03")),
        status="COMPLETED",
        final="UNKNOWN_LOCATION",
    )
    mismatch = next(f for f in report.findings if f.rule_id == "TRANSACTION_OUTCOME_MISMATCH")
    assert mismatch.diagnosis_class == "APPLICATION_FAILURE"
    assert mismatch.category == "SOFTWARE"
    assert mismatch.severity == "HIGH"
    assert "CASH_ACCEPTED_NOT_STORED" in ids(report)


# ---------------------------------------------------------------------------
# host vs hardware / communication / reconciliation extras
# ---------------------------------------------------------------------------


def test_communication_failure_when_host_never_responds():
    report = run(
        P2600,
        [
            ev("CASH_ACCEPTED", T("10:05:02"), line=1),
            ev("HOST_REQUEST", T("10:05:05"), "HOST_REQUEST TXN=T REF=HR-1", line=2),
            ev("CASH_RETURNED", T("10:06:00"), line=3),
            ev("TRANSACTION_FAILED", T("10:06:05"), line=4),
        ],
        movements=cash(["ACCEPTED", "RETURNED"], T("10:05:02")),
        status="FAILED",
        final="RETURNED",
    )
    finding = next(f for f in report.findings if f.rule_id == "HOST_NO_RESPONSE")
    assert finding.category == "COMMUNICATION"
    assert finding.diagnosis_class == "COMMUNICATION_FAILURE"


def test_amount_mismatch_reconciliation():
    report = run(
        P2600,
        [
            ev("CASH_INSERTED", T("10:00:02"), "CASH_INSERTED TXN=T AMOUNT=500.00 NOTES=5", line=2),
            ev("CASH_COUNTING_COMPLETED", T("10:00:04"), "COUNTING_COMPLETED TXN=T AMOUNT=400.00 NOTES=5", line=4),
            ev("CASH_STORED", T("10:00:10"), line=6),
            ev("TRANSACTION_COMPLETED", T("10:00:11"), line=7),
        ],
        movements=cash(["INSERTED", "COUNTED", "STORED"], T("10:00:02")),
        status="COMPLETED",
        final="STORED",
    )
    mismatch = next(f for f in report.findings if f.rule_id == "CASH_AMOUNT_MISMATCH")
    assert mismatch.category == "CASH_HANDLING"
    assert mismatch.diagnosis_class == "CASH_EXCEPTION"
    recon = next(e for e in mismatch.evidence if e["kind"] == "reconciliation")
    assert recon["issue"] == "AMOUNT_MISMATCH"
    assert recon["detail"]["inserted_amount"] == 500.0
    assert recon["detail"]["counted_amount"] == 400.0


def test_matching_amounts_do_not_fire_mismatch():
    report = run(
        P2600,
        [
            ev("CASH_INSERTED", T("10:00:02"), "CASH_INSERTED TXN=T AMOUNT=500.00 NOTES=5", line=2),
            ev("CASH_COUNTING_COMPLETED", T("10:00:04"), "COUNTING_COMPLETED TXN=T AMOUNT=500.00 NOTES=5", line=4),
            ev("CASH_STORED", T("10:00:10"), line=6),
            ev("TRANSACTION_COMPLETED", T("10:00:11"), line=7),
        ],
        movements=cash(["INSERTED", "COUNTED", "STORED"], T("10:00:02")),
        status="COMPLETED",
        final="STORED",
    )
    assert "CASH_AMOUNT_MISMATCH" not in ids(report)
    assert "NORMAL_COMPLETION" in ids(report)


def test_missing_amount_side_never_fires_mismatch():
    # P2800N has no note-count pattern configured → COUNT_MISMATCH impossible.
    report = run(
        P2800,
        [
            ev("CASH_ACCEPTED", T("10:00:02"), "ESCROW_IN amt=100.00", line=2),
            ev("CASH_COUNTING_COMPLETED", T("10:00:04"), "NOTES_COUNTED amt=100.00", line=4),
            ev("CASH_STORED", T("10:00:10"), line=6),
            ev("TRANSACTION_COMPLETED", T("10:00:11"), line=7),
        ],
        movements=cash(["ACCEPTED", "COUNTED", "STORED"], T("10:00:02")),
        status="COMPLETED",
        final="STORED",
    )
    assert "CASH_COUNT_MISMATCH" not in ids(report)


def test_evidence_structure_complete_on_every_finding():
    report = run(
        P2800,
        [
            ev("CASH_ACCEPTED", T("10:20:02"), "ESCROW_IN amt=100.00", line=2),
            ev("JAM_DETECTED", T("10:20:09"), "|APP|ERR|JAM|TRANSPORT", line=3, detail={"error_code": "P28APP-JAM"}),
            ev("TRANSPORT_TIMEOUT", T("10:20:26"), line=4),
        ],
        movements=cash(["ACCEPTED", "JAMMED"], T("10:20:02")),
        status="FAILED",
        final="JAMMED",
        faults=[NS(classification="CONFIRMED_JAM", subject_kind="transport",
                   subject_name="TRANSPORT", statement="Jam confirmed.")],
    )
    assert report.findings
    for f in report.findings:
        # section 3 structure
        assert f.finding_id and f.diagnosis_class and f.severity and f.confidence
        assert f.summary and f.interpretation
        assert f.confidence in ("LOW", "MODERATE", "HIGH", "VERY_HIGH")
        assert f.category in {None} | {
            "HARDWARE", "SOFTWARE", "FIRMWARE", "CONFIGURATION", "HOST", "NETWORK",
            "COMMUNICATION", "SENSOR", "MOTOR", "GATE", "SHUTTER", "TRANSPORT",
            "CASH_HANDLING", "UNKNOWN",
        }
        # section 4: evidence references raw lines wherever the finding
        # claims log evidence (fault-only refs excepted)
        for e in f.evidence:
            if e.get("kind") in ("event", "cash"):
                assert {"file_id", "line_number", "raw_text"} <= set(e)
                assert e["timestamp"]
