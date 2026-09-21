"""Structured AI-input digest (Phase 8, spec §1).

Builds a compact, fully structured description of one transaction from the
already-normalized data: transaction summary, normalized events, cash
states, host events, hardware events, rule results, root-cause candidates
and evidence. Raw log lines appear ONLY as short evidence excerpts (file +
line + truncated text) — full log files are never included.

Everything is deterministic and bounded (see ``BOUNDS``); the digest is the
single input both the deterministic composer and any external LLM receive.
"""

from __future__ import annotations

import hashlib
import json
from sqlalchemy.orm import Session

from app.models.log_file import LogFile
from app.models.transaction import Transaction
from app.services.diagnostic_service import diagnostic_service
from app.services.hardware_service import hardware_service
from app.services.transaction_service import transaction_service

# Bounds — "do not blindly send huge raw log files".
BOUNDS = {
    "max_events": 300,
    "max_evidence": 200,
    "max_raw_chars": 240,
    "max_detail_chars": 400,
}

_CONF_RANK = {"VERY_HIGH": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}

_HOST_EVENTS = ("HOST_REQUEST", "HOST_RESPONSE", "HOST_DECLINED")
_ERROR_EVENTS = ("ERROR", "VALIDATION_FAILED")


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt if isinstance(dt, str) else dt.isoformat()


def _clip(value: str | None, limit: int) -> str:
    if not value:
        return ""
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 3] + "…"


class EvidenceRegistry:
    """Deduplicating file:line evidence registry with stable EV identifiers."""

    def __init__(self) -> None:
        self._items: list[dict] = []
        self._index: dict[tuple[str, int], str] = {}

    def add(
        self,
        file_id: str | None,
        line_number: int | None,
        raw_text: str | None,
        origin: str,
    ) -> str | None:
        if not file_id or line_number is None:
            return None
        key = (file_id, line_number)
        if key in self._index:
            return self._index[key]
        if len(self._items) >= BOUNDS["max_evidence"]:
            return None
        ev_id = f"EV-{len(self._items) + 1:03d}"
        self._index[key] = ev_id
        self._items.append(
            {
                "id": ev_id,
                "file_id": file_id,
                "line_number": line_number,
                "raw_excerpt": _clip(raw_text, BOUNDS["max_raw_chars"]),
                "origin": origin,
            }
        )
        return ev_id

    @property
    def items(self) -> list[dict]:
        return self._items

    def ids(self) -> set[str]:
        return set(self._index.values())


def build_digest(session: Session, txn: Transaction) -> dict:
    """Assemble the Phase-8 AI input digest for one transaction."""
    # ---- underlying analyses (all deterministic, already stored) ----------
    timeline = transaction_service.timeline(session, txn.id)  # {txn_id} = UUID pk
    from app.schemas.hardware import HardwareTimelineOut

    hw = HardwareTimelineOut.model_validate(
        hardware_service.hardware_payload(session, txn), from_attributes=True
    ).model_dump(mode="json")
    from app.schemas.diagnostics import DiagnosticReportOut

    report = DiagnosticReportOut.model_validate(
        diagnostic_service.report(session, txn), from_attributes=True
    ).model_dump(mode="json")

    ev = EvidenceRegistry()

    # ---- machine / model ---------------------------------------------------
    machine = txn.machine
    model = txn.machine_model
    machine_block = None
    if machine is not None:
        machine_block = {
            "machine_id": machine.id,
            "serial_number": machine.serial_number,
            "name": machine.name,
            "location": machine.location,
            "status": machine.status,
            "model_code": model.code if model else txn.model_code,
            "model_name": model.name if model else None,
            "vendor": model.vendor if model else None,
        }

    # ---- normalized events (with evidence references) ----------------------
    events_out: list[dict] = []
    truncated_events = False
    for entry in timeline["entries"]:
        if len(events_out) >= BOUNDS["max_events"]:
            truncated_events = True
            break
        raw = entry.get("raw") or {}
        events_out.append(
            {
                "timestamp": _iso(entry.get("timestamp")),
                "event": entry["event"],
                "stage": entry.get("stage"),
                "device": entry.get("device"),
                "severity": entry.get("severity", "INFO"),
                "source": entry.get("source"),
                "evidence_id": ev.add(
                    raw.get("file_id"), raw.get("line_number"), raw.get("raw_text"), "timeline"
                ),
            }
        )

    # ---- cash states --------------------------------------------------------
    cash_movements = []
    for m in hw["cash_movements"]:
        cash_movements.append(
            {
                "note_id": m.get("note_id"),
                "from_state": m.get("from_state"),
                "to_state": m.get("to_state"),
                "timestamp": _iso(m.get("timestamp")),
                "device": m.get("device"),
                "confidence": m.get("confidence"),
                "evidence_id": ev.add(m.get("log_file_id"), m.get("line_number"), m.get("raw_text"), "cash"),
            }
        )

    # ---- host events ---------------------------------------------------------
    host_events = [
        e for e in events_out if e["event"] in _HOST_EVENTS or (e.get("stage") or "").startswith("host_")
    ]

    # ---- error events ---------------------------------------------------------
    error_events = []
    for entry in timeline["entries"]:
        if entry["event"] in _ERROR_EVENTS:
            detail = entry.get("detail") or {}
            raw = entry.get("raw") or {}
            error_events.append(
                {
                    "timestamp": _iso(entry.get("timestamp")),
                    "event": entry["event"],
                    "error_code": detail.get("error_code"),
                    "error_description": detail.get("error_description"),
                    "device": entry.get("device"),
                    "source": entry.get("source"),
                    "evidence_id": ev.add(
                        raw.get("file_id"), raw.get("line_number"), raw.get("raw_text"), "error"
                    ),
                }
            )

    # ---- hardware events -------------------------------------------------------
    def hw_common(record: dict, origin: str) -> dict:
        return {
            "evidence_id": ev.add(
                record.get("log_file_id"), record.get("line_number"), record.get("raw_text"), origin
            )
        }

    hardware_events = {
        "sensors": [
            {
                "sensor": s.get("sensor"),
                "previous_state": s.get("previous_state"),
                "new_state": s.get("new_state"),
                "expected_state": s.get("expected_state"),
                "actual_state": s.get("actual_state"),
                "abnormal_duration_ms": s.get("abnormal_duration_ms"),
                "timestamp": _iso(s.get("timestamp")),
                **hw_common(s, "sensor"),
            }
            for s in hw["sensor_events"]
        ],
        "motors": [
            {
                "motor": m.get("motor"),
                "started_at": _iso(m.get("started_at")),
                "stopped_at": _iso(m.get("stopped_at")),
                "duration_ms": m.get("duration_ms"),
                "timeout_ms": m.get("timeout_ms"),
                "timed_out": m.get("timed_out"),
                "device": m.get("device"),
                **hw_common(m, "motor"),
            }
            for m in hw["motor_events"]
        ],
        "gates": [
            {
                "kind": g.get("kind"),
                "name": g.get("name"),
                "expected_state": g.get("expected_state"),
                "actual_state": g.get("actual_state"),
                "timed_out": g.get("timed_out"),
                "state_mismatch": g.get("state_mismatch"),
                **hw_common(g, "gate"),
            }
            for g in hw["gate_events"] + hw["shutter_events"]
        ],
        "transports": [
            {
                "name": t.get("name"),
                "outcome": t.get("outcome"),
                "started_at": _iso(t.get("started_at")),
                "ended_at": _iso(t.get("ended_at")),
                "timeout_ms": t.get("timeout_ms"),
                **hw_common(t, "transport"),
            }
            for t in hw["transport_events"]
        ],
        "faults": [
            {
                "subject_kind": f.get("subject_kind"),
                "subject_name": f.get("subject_name"),
                "classification": f.get("classification"),
                "statement": f.get("statement"),
                "evidence_ids": [
                    ev.add(evi.get("file_id"), evi.get("line_number"), evi.get("raw_text"), "fault")
                    for evi in (f.get("evidence") or [])
                ],
            }
            for f in hw["faults"]
        ],
    }

    # ---- rule results -----------------------------------------------------------
    rule_results = []
    for f in report["findings"]:
        ev_ids = [
            ev_id
            for ev_id in (
                ev.add(evi.get("file_id"), evi.get("line_number"), evi.get("raw_text"), f"rule:{f['rule_id']}")
                for evi in (f.get("evidence") or [])
            )
            if ev_id
        ]
        rule_results.append(
            {
                "rule_id": f["rule_id"],
                "diagnosis_class": f["diagnosis_class"],
                "severity": f["severity"],
                "confidence": f["confidence"],
                "summary": f["summary"],
                "interpretation": f["interpretation"],
                "possible_causes": f.get("possible_causes") or [],
                "recommended_action": f.get("recommended_action"),
                "evidence_ids": ev_ids,
            }
        )

    # ---- root-cause candidates (ranked from the rule results) --------------------
    candidates = sorted(
        (
            r
            for r in rule_results
            if r["rule_id"] != "NORMAL_COMPLETION"
        ),
        key=lambda r: (_CONF_RANK.get(r["confidence"], 9), r["severity"] != "CRITICAL"),
    )
    from app.ai.safety import epistemic_from_confidence

    root_cause_candidates = [
        {
            "candidate": r["rule_id"],
            "statement": r["summary"],
            "diagnosis_class": r["diagnosis_class"],
            "confidence": r["confidence"],
            "epistemic_label": epistemic_from_confidence(r["confidence"]),
            "evidence_ids": r["evidence_ids"],
        }
        for r in candidates
    ]

    # ---- filenames for evidence ---------------------------------------------------
    file_ids = {item["file_id"] for item in ev.items}
    filenames: dict[str, str] = {}
    if file_ids:
        for row in session.query(LogFile.id, LogFile.original_filename).filter(LogFile.id.in_(file_ids)).all():
            filenames[row[0]] = row[1]
    evidence = [
        {**item, "file": filenames.get(item["file_id"], item["file_id"][:8])} for item in ev.items
    ]

    digest = {
        "transaction": {
            "id": txn.id,
            "transaction_id": txn.transaction_id,
            "model_code": txn.model_code,
            "status": txn.status,
            "start_time": _iso(txn.start_time),
            "end_time": _iso(txn.end_time),
            "amount": txn.amount,
            "currency": txn.currency,
            "correlation_confidence": txn.correlation_confidence,
            "correlation_method": txn.correlation_method,
            "stages_confirmed": timeline["stages_confirmed"],
            "stages_not_confirmed": timeline.get("stages_not_confirmed", []),
            "lifecycle_complete": timeline["complete"],
        },
        "machine": machine_block,
        "normalized_events": events_out,
        "cash_states": {
            "final_cash_state": hw["final_cash_state"],
            "movements": cash_movements,
        },
        "host_events": host_events,
        "error_events": error_events,
        "hardware_events": hardware_events,
        "rule_results": rule_results,
        "engine_report": {
            "classification": report["classification"],
            "diagnosis_class": report["diagnosis_class"],
            "severity": report["severity"],
            "confidence": report["confidence"],
            "summary": report["summary"],
            "final_cash_state": report.get("final_cash_state"),
        },
        "root_cause_candidates": root_cause_candidates,
        "evidence": evidence,
        "bounds": {
            **BOUNDS,
            "events_included": len(events_out),
            "events_total": len(timeline["entries"]),
            "events_truncated": truncated_events,
            "evidence_count": len(evidence),
        },
        "note": (
            "Structured digest only — full raw log files are never sent. "
            "All facts must trace to the listed evidence identifiers."
        ),
    }
    digest["digest_sha256"] = hashlib.sha256(
        json.dumps(digest, sort_keys=True, default=str).encode()
    ).hexdigest()
    return digest
