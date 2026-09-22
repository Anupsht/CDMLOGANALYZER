"""Phase 9 — historical analytics, pattern detection, cross-machine analysis.

Read-only aggregation over the stored, universal evidence picture
(transactions, universal event codes, Phase-5 findings, hardware tables).
Nothing here reinterprets stored data and nothing here feeds back into the
deterministic engines: detected patterns become *suggestions* that require
explicit human review before a human manually promotes them (YAML) — the
production rule engine never imports from this module.

Cross-DB strategy: rows are filtered/bounded in SQL, bucketed/aggregated in
Python (SQLite dev / MySQL prod compatible).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.diagnostics import DiagnosticFinding
from app.models.hardware import CashMovement, SensorEvent
from app.models.log_file import LogFile, LogLine
from app.models.machine import Machine
from app.models.transaction import Transaction, TransactionEvent
from app.core.registry import model_registry

# Universal event-code groups (query logic only — no reinterpretation).
_JAM_EVENTS = ("JAM_DETECTED",)
_HW_EVENT_CODES = (
    "JAM_DETECTED", "JAM_CLEARED", "TRANSPORT_TIMEOUT", "DEVICE_UNAVAILABLE",
    "VALIDATION_FAILED", "GATE_POSITION", "MOTOR_STOPPED",
)
_ERROR_EVENTS = ("ERROR", "VALIDATION_FAILED")
_RESET_PATTERNS = ("%RESET%", "%JAM_CLEARED%")
_DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"
_DENOM_KEYS = ("denomination", "denom", "value", "note_value")

# Detection thresholds (heuristic, documented in the API response).
PATTERN_MIN_REPEATS = 2  # 2+ occurrences = repeated; confidence stays low
PATTERN_TIME_SHARE = 0.45  # share of events in one hour-bucket to flag
PATTERN_MODEL_SHARE = 0.8  # share concentrated in one model to flag


def _cutoff(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


def _bucket_key(dt: datetime, bucket: str) -> str:
    if bucket == "monthly":
        return dt.strftime("%Y-%m")
    if bucket == "weekly":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return dt.strftime("%Y-%m-%d")


def _txn_window(session: Session, window_days: int):
    """Bounded (id, machine_id, model_code, start_time, status) rows."""
    rows = (
        session.query(
            Transaction.id,
            Transaction.machine_id,
            Transaction.model_code,
            Transaction.start_time,
            Transaction.status,
        )
        .filter(
            or_(Transaction.start_time.is_(None), Transaction.start_time >= _cutoff(window_days))
        )
        .all()
    )
    return rows


def _finding_counts(session: Session, txn_ids: list[str]) -> dict:
    if not txn_ids:
        return {"hardware_errors": 0, "jams": 0, "cash_exceptions": 0, "host_failures": 0}
    # NOTE: sum() over a boolean expression is driver-coerced on SQLite
    # (sum(9) → True) — group in SQL, aggregate in Python instead.
    rows = (
        session.query(DiagnosticFinding.diagnosis_class, DiagnosticFinding.rule_id, func.count())
        .filter(DiagnosticFinding.transaction_id.in_(txn_ids))
        .group_by(DiagnosticFinding.diagnosis_class, DiagnosticFinding.rule_id)
        .all()
    )
    hw = jam = cash = host = 0
    for diag_class, rule_id, count in rows:
        count = int(count)
        if diag_class == "HARDWARE_FAILURE":
            hw += count
        if rule_id in ("POSSIBLE_CASH_JAM", "CONFIRMED_CASH_JAM"):
            jam += count
        if diag_class == "CASH_EXCEPTION":
            cash += count
        if diag_class == "HOST_FAILURE":
            host += count
    return {"hardware_errors": hw, "jams": jam, "cash_exceptions": cash, "host_failures": host}


# --------------------------------------------------------------------------- #
# §1 + §5 — historical analytics & trends
# --------------------------------------------------------------------------- #


def overview(session: Session, *, window_days: int = 90) -> dict:
    rows = _txn_window(session, window_days)
    txn_ids = [r.id for r in rows]
    findings = _finding_counts(session, txn_ids)

    # device-unavailable + reset/recovery event counters
    base = (
        session.query(TransactionEvent.event_code)
        .filter(TransactionEvent.transaction_id.in_(txn_ids))
    )
    device_unavailable = 0
    resets = 0
    error_events = 0
    for (code,) in base.all():
        if code == _DEVICE_UNAVAILABLE:
            device_unavailable += 1
        elif code == "JAM_CLEARED" or "RESET" in (code or ""):
            resets += 1
        if code in _ERROR_EVENTS:
            error_events += 1

    sensor_faults = (
        session.query(func.count(SensorEvent.id))
        .filter(SensorEvent.abnormal_duration_ms.isnot(None))
    )
    if txn_ids:
        sensor_faults = sensor_faults.filter(SensorEvent.transaction_id.in_(txn_ids))
    sensor_faults = int(sensor_faults.scalar() or 0)

    failed = sum(1 for r in rows if r.status in ("FAILED", "DECLINED", "INCOMPLETE"))
    return {
        "window_days": window_days,
        "transactions": {
            "total": len(rows),
            "completed": sum(1 for r in rows if r.status == "COMPLETED"),
            "failed": failed,
            "failed_status_only": sum(1 for r in rows if r.status == "FAILED"),
            "declined": sum(1 for r in rows if r.status == "DECLINED"),
            "incomplete": sum(1 for r in rows if r.status == "INCOMPLETE"),
        },
        "failures": findings["host_failures"],
        "errors": error_events,
        "jams": findings["jams"],
        "sensor_faults": sensor_faults,
        "cash_exceptions": findings["cash_exceptions"],
        "host_failures": findings["host_failures"],
        "hardware_errors": findings["hardware_errors"],
        "device_unavailable_events": device_unavailable,
        "automatic_resets": resets,
    }


def trends(session: Session, *, bucket: str = "daily", window_days: int = 90) -> dict:
    """Bucketed series (§5): transactions, failures, jams, errors, hw events."""
    if bucket not in ("daily", "weekly", "monthly"):
        from app.core.errors import ValidationError

        raise ValidationError(f"invalid bucket: {bucket} (daily|weekly|monthly)")

    rows = _txn_window(session, window_days)
    txn_ids = [r.id for r in rows]

    # jam + error events per transaction (bounded fetch)
    jam_by_txn: Counter[str] = Counter()
    error_by_txn: Counter[str] = Counter()
    if txn_ids:
        for tid, code in (
            session.query(TransactionEvent.transaction_id, TransactionEvent.event_code)
            .filter(TransactionEvent.transaction_id.in_(txn_ids))
            .filter(
                or_(
                    TransactionEvent.event_code.in_(_JAM_EVENTS),
                    TransactionEvent.event_code.in_(_ERROR_EVENTS),
                )
            )
            .all()
        ):
            if code in _JAM_EVENTS:
                jam_by_txn[tid] += 1
            else:
                error_by_txn[tid] += 1

    series: dict[str, dict[str, dict]] = defaultdict(lambda: {"transactions": 0, "failures": 0, "jams": 0, "errors": 0})

    def touch(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return _bucket_key(dt, bucket)

    for r in rows:
        key = touch(r.start_time)
        if key is None:
            continue
        s = series[key]
        s["transactions"] += 1
        if r.status in ("FAILED", "DECLINED", "INCOMPLETE"):
            s["failures"] += 1
        s["jams"] += jam_by_txn.get(r.id, 0)
        s["errors"] += error_by_txn.get(r.id, 0)

    points = [
        {"bucket": k, **{m: series[k][m] for m in ("transactions", "failures", "jams", "errors")}}
        for k in sorted(series)
    ]
    return {
        "bucket": bucket,
        "window_days": window_days,
        "points": points,
        "note": "Counts derive from stored transactions/universal event codes; buckets are UTC.",
    }


# --------------------------------------------------------------------------- #
# §4 — error analytics
# --------------------------------------------------------------------------- #


def error_analytics(session: Session, *, window_days: int = 90, limit: int = 50) -> dict:
    """Per-error-code stats incl. common preceding/following events (§4)."""
    rows = _txn_window(session, window_days)
    txn_ids = {r.id for r in rows}
    if not txn_ids:
        return {"window_days": window_days, "errors": [], "note": "no transactions in window"}

    events = (
        session.query(
            TransactionEvent.transaction_id,
            TransactionEvent.event_code,
            TransactionEvent.seq,
            TransactionEvent.timestamp,
            TransactionEvent.detail,
        )
        .filter(TransactionEvent.transaction_id.in_(txn_ids))
        .order_by(TransactionEvent.transaction_id, TransactionEvent.seq)
        .all()
    )
    # group per transaction for neighbor analysis
    by_txn: dict[str, list] = defaultdict(list)
    for tid, code, seq, ts, detail in events:
        by_txn[tid].append((code, ts, detail or {}))

    stats: dict[str, dict] = {}
    machine_of = {r.id: r.machine_id for r in rows}
    model_of = {r.id: r.model_code for r in rows}

    for tid, evs in by_txn.items():
        for idx, (code, ts, detail) in enumerate(evs):
            if code not in _ERROR_EVENTS:
                continue
            error_code = detail.get("error_code") or code
            entry = stats.setdefault(
                error_code,
                {
                    "error_code": error_code,
                    "event_code": code,
                    "occurrence_count": 0,
                    "machines_affected": set(),
                    "models_affected": set(),
                    "first_occurrence": None,
                    "last_occurrence": None,
                    "preceding_events": Counter(),
                    "following_events": Counter(),
                    "sample_transaction_ids": [],
                },
            )
            entry["occurrence_count"] += 1
            if machine_of.get(tid):
                entry["machines_affected"].add(machine_of[tid])
            if model_of.get(tid):
                entry["models_affected"].add(model_of[tid])
            stamp = ts.isoformat() if ts else None
            if stamp:
                if entry["first_occurrence"] is None or stamp < entry["first_occurrence"]:
                    entry["first_occurrence"] = stamp
                if entry["last_occurrence"] is None or stamp > entry["last_occurrence"]:
                    entry["last_occurrence"] = stamp
            if len(entry["sample_transaction_ids"]) < 5:
                entry["sample_transaction_ids"].append(tid)
            if idx > 0:
                entry["preceding_events"][evs[idx - 1][0]] += 1
            if idx + 1 < len(evs):
                entry["following_events"][evs[idx + 1][0]] += 1

    out = []
    for entry in stats.values():
        out.append(
            {
                "error_code": entry["error_code"],
                "event_code": entry["event_code"],
                "occurrence_count": entry["occurrence_count"],
                "machines_affected": len(entry["machines_affected"]),
                "models_affected": sorted(entry["models_affected"]),
                "first_occurrence": entry["first_occurrence"],
                "last_occurrence": entry["last_occurrence"],
                "common_preceding_events": [
                    {"event": k, "count": v}
                    for k, v in entry["preceding_events"].most_common(5)
                ],
                "common_following_events": [
                    {"event": k, "count": v}
                    for k, v in entry["following_events"].most_common(5)
                ],
                "sample_transaction_ids": entry["sample_transaction_ids"],
            }
        )
    out.sort(key=lambda e: -e["occurrence_count"])
    return {
        "window_days": window_days,
        "errors": out[:limit],
        "note": (
            "Preceding/following events are the chronologically adjacent normalized "
            "events inside the same transaction — correlation, not causation."
        ),
    }


# --------------------------------------------------------------------------- #
# §2 — pattern detection
# --------------------------------------------------------------------------- #


def _pattern_base(kind: str, description: str, stats: dict, confidence: str) -> dict:
    return {
        "pattern_type": kind,
        "description": description,
        "stats": stats,
        "confidence": confidence,
        "rule_suggestion_draft": _draft_for(kind, description, stats),
    }


def _draft_for(kind: str, description: str, stats: dict) -> dict:
    """A DRAFT rule mirroring the diagnostics rules.yaml shape.

    Drafts are inert: they are suggestions for human review only and are
    never loaded by the production rules engine.
    """
    base = {
        "draft_kind": kind,
        "draft_description": description,
        "requires_human_review": True,
        "production_note": (
            "Never auto-loaded. A human must review, adapt thresholds and copy the "
            "rule into config/diagnostics/rules.yaml (or a model overlay) — the "
            "YAML-only swap path of the rules engine."
        ),
    }
    if kind == "repeated_error":
        base["draft_rule"] = {
            "id": f"SUGGESTED_REPEAT_ERROR_{re.sub(r'[^A-Z0-9]+', '_', stats.get('error_code', 'X')).strip('_')}",
            "trigger": {"event": "ERROR", "error_code": stats.get("error_code")},
            "min_occurrences": stats.get("occurrence_count"),
            "diagnosis_class": "APPLICATION_FAILURE",
            "severity": "WARNING",
            "confidence": "MODERATE",
            "summary": f"Recurring error {stats.get('error_code')} across transactions",
        }
    elif kind == "repeated_sensor_abnormality":
        base["draft_rule"] = {
            "id": f"SUGGESTED_REPEAT_SENSOR_{re.sub(r'[^A-Za-z0-9]+', '_', stats.get('sensor', 'X')).strip('_').upper()}",
            "sensor": stats.get("sensor"),
            "min_abnormal_count": stats.get("abnormal_count"),
            "diagnosis_class": "HARDWARE_FAILURE",
            "severity": "WARNING",
            "confidence": "LOW",
            "summary": f"Sensor {stats.get('sensor')} abnormal in {stats.get('abnormal_count')} transactions",
        }
    elif kind == "repeated_jam_location":
        base["draft_rule"] = {
            "id": f"SUGGESTED_JAM_LOCATION_{re.sub(r'[^A-Za-z0-9]+', '_', str(stats.get('device', 'X'))).strip('_').upper()}",
            "trigger": {"event": "JAM_DETECTED", "device": stats.get("device")},
            "min_occurrences": stats.get("occurrence_count"),
            "diagnosis_class": "HARDWARE_FAILURE",
            "severity": "CRITICAL",
            "confidence": "MODERATE",
            "summary": f"Repeated jams at {stats.get('device')} — inspect that path",
        }
    elif kind == "time_pattern":
        base["draft_rule"] = {
            "id": f"SUGGESTED_TIME_CONCENTRATION_{re.sub(r'[^A-Za-z0-9]+', '_', str(stats.get('kind', 'X'))).strip('_').upper()}",
            "time_window": {"hours": stats.get("hours")},
            "event": stats.get("event"),
            "share_of_occurrences": stats.get("share"),
            "diagnosis_class": "COMMUNICATION_FAILURE",
            "severity": "INFO",
            "confidence": "LOW",
            "summary": f"{stats.get('kind')} concentrated around hours {stats.get('hours')}",
        }
    elif kind == "model_pattern":
        base["draft_rule"] = {
            "id": f"SUGGESTED_MODEL_PATTERN_{re.sub(r'[^A-Za-z0-9]+', '_', str(stats.get('model_code', 'X'))).strip('_').upper()}",
            "model_code": stats.get("model_code"),
            "event": stats.get("event"),
            "share_of_occurrences": stats.get("share"),
            "diagnosis_class": "APPLICATION_FAILURE",
            "severity": "INFO",
            "confidence": "LOW",
            "summary": f"{stats.get('event')} concentrated on model {stats.get('model_code')}",
        }
    elif kind == "repeated_machine_failure":
        base["draft_rule"] = {
            "id": "SUGGESTED_MACHINE_FAILURE_REPEAT",
            "machine_id": stats.get("machine_id"),
            "min_failed_transactions": stats.get("failed_incomplete_count"),
            "diagnosis_class": "INSUFFICIENT_DATA",
            "severity": "WARNING",
            "confidence": "LOW",
            "summary": (
                f"Machine {stats.get('machine_id')} repeated FAILED/INCOMPLETE "
                f"transactions — investigate, do not auto-classify"
            ),
        }
    elif kind == "denomination_pattern":
        base["draft_rule"] = {
            "id": f"SUGGESTED_DENOMINATION_{re.sub(r'[^A-Za-z0-9]+', '_', str(stats.get('denomination', 'X'))).strip('_')}",
            "denomination": stats.get("denomination"),
            "jams_or_rejects": stats.get("count"),
            "diagnosis_class": "CASH_EXCEPTION",
            "severity": "WARNING",
            "confidence": "LOW",
            "summary": f"Exceptions cluster on denomination {stats.get('denomination')}",
        }
    return base


def patterns(session: Session, *, window_days: int = 90) -> dict:
    """Detect the §2 pattern families. Every pattern is advisory only."""
    rows = _txn_window(session, window_days)
    txn_ids = [r.id for r in rows]
    machine_of = {r.id: r.machine_id for r in rows}
    model_of = {r.id: (r.model_code or "UNKNOWN") for r in rows}
    found: list[dict] = []
    if not txn_ids:
        return {"window_days": window_days, "patterns": found, "thresholds": {"min_repeats": PATTERN_MIN_REPEATS}}

    events = (
        session.query(
            TransactionEvent.transaction_id,
            TransactionEvent.event_code,
            TransactionEvent.device,
            TransactionEvent.timestamp,
            TransactionEvent.detail,
        )
        .filter(TransactionEvent.transaction_id.in_(txn_ids))
        .order_by(TransactionEvent.transaction_id, TransactionEvent.seq)
        .all()
    )

    # ---- repeated errors -----------------------------------------------------
    err_stats: dict[str, Counter] = defaultdict(Counter)  # code -> model counter
    err_counts: Counter = Counter()
    for tid, code, dev, ts, detail in events:
        if code in _ERROR_EVENTS:
            error_code = (detail or {}).get("error_code") or code
            err_counts[error_code] += 1
            err_stats[error_code][model_of.get(tid, "UNKNOWN")] += 1
    for code, count in err_counts.most_common():
        if count >= PATTERN_MIN_REPEATS:
            models = dict(err_stats[code])
            stats = {
                "error_code": code,
                "occurrence_count": count,
                "per_model": models,
            }
            confidence = "POSSIBLE" if count >= 2 * PATTERN_MIN_REPEATS else "UNKNOWN"
            found.append(
                _pattern_base(
                    "repeated_error",
                    f"Error {code} occurred {count}× in the window (per model: {models}).",
                    stats,
                    confidence,
                )
            )

    # ---- repeated sensor abnormalities ----------------------------------------
    sensor_counts: Counter = Counter()
    sensor_models: dict[str, Counter] = defaultdict(Counter)
    sq = session.query(SensorEvent.sensor, SensorEvent.transaction_id).filter(
        SensorEvent.abnormal_duration_ms.isnot(None)
    )
    if txn_ids:
        sq = sq.filter(SensorEvent.transaction_id.in_(txn_ids))
    for sensor, tid in sq.all():
        sensor_counts[sensor] += 1
        sensor_models[sensor][model_of.get(tid, "UNKNOWN")] += 1
    for sensor, count in sensor_counts.most_common():
        if count >= PATTERN_MIN_REPEATS:
            stats = {"sensor": sensor, "abnormal_count": count, "per_model": dict(sensor_models[sensor])}
            found.append(
                _pattern_base(
                    "repeated_sensor_abnormality",
                    f"Sensor {sensor} abnormal in {count} transactions.",
                    stats,
                    "UNKNOWN",
                )
            )

    # ---- repeated jam locations -------------------------------------------------
    jam_devices: Counter = Counter()
    jam_models: dict[str, Counter] = defaultdict(Counter)
    for tid, code, device, ts, detail in events:
        if code in _JAM_EVENTS:
            dev = device or "unspecified"
            jam_devices[dev] += 1
            jam_models[dev][model_of.get(tid, "UNKNOWN")] += 1
    for dev, count in jam_devices.most_common():
        if count >= PATTERN_MIN_REPEATS:
            stats = {"device": dev, "occurrence_count": count, "per_model": dict(jam_models[dev])}
            found.append(
                _pattern_base(
                    "repeated_jam_location",
                    f"{count} jams at device '{dev}' — recurring location.",
                    stats,
                    "POSSIBLE",
                )
            )

    # ---- time-based patterns (hour-of-day concentration) -------------------------
    hour_buckets: dict[str, Counter] = defaultdict(Counter)  # event -> hour counter
    hour_totals: Counter = Counter()
    for tid, code, dev, ts, detail in events:
        if code in _JAM_EVENTS or code in _ERROR_EVENTS or code == _DEVICE_UNAVAILABLE:
            if ts is not None:
                hour = ts.hour if not isinstance(ts, str) else int(ts[11:13])
                kind = "jams" if code in _JAM_EVENTS else ("device_unavailable" if code == _DEVICE_UNAVAILABLE else "errors")
                hour_buckets[kind][hour] += 1
                hour_totals[kind] += 1
    for kind, hours in hour_buckets.items():
        total = hour_totals[kind]
        if total < PATTERN_MIN_REPEATS:
            continue
        top_hour, top_count = hours.most_common(1)[0]
        share = round(top_count / total, 2)
        if top_count >= PATTERN_MIN_REPEATS and share >= PATTERN_TIME_SHARE:
            # neighbor hours merged for the description
            center = top_hour
            near = hours.get((center - 1) % 24, 0) + hours.get((center + 1) % 24, 0)
            stats = {
                "kind": kind,
                "hours": [center],
                "occurrences": top_count,
                "total": total,
                "share": share,
            }
            if near / total >= PATTERN_TIME_SHARE:
                stats["hours"] = sorted({(center - 1) % 24, center, (center + 1) % 24})
            found.append(
                _pattern_base(
                    "time_pattern",
                    f"{kind} cluster around {stats['hours']}:00 UTC "
                    f"({top_count}/{total}, share {share}).",
                    stats,
                    "UNKNOWN",
                )
            )

    # ---- model-specific patterns ---------------------------------------------------
    model_event_counts: dict[str, Counter] = defaultdict(Counter)
    event_totals: Counter = Counter()
    for tid, code, dev, ts, detail in events:
        if code in _ERROR_EVENTS or code in _JAM_EVENTS or code == _DEVICE_UNAVAILABLE:
            mc = model_of.get(tid, "UNKNOWN")
            model_event_counts[code][mc] += 1
            event_totals[code] += 1
    for code, per_model in model_event_counts.items():
        total = event_totals[code]
        if total < PATTERN_MIN_REPEATS or len(per_model) < 2:
            continue
        top_model, top_count = per_model.most_common(1)[0]
        share = round(top_count / total, 2)
        if share >= PATTERN_MODEL_SHARE:
            stats = {"event": code, "model_code": top_model, "occurrences": top_count, "total": total, "share": share}
            found.append(
                _pattern_base(
                    "model_pattern",
                    f"{code} concentrated on {top_model} ({top_count}/{total}).",
                    stats,
                    "UNKNOWN",
                )
            )

    # ---- denomination patterns -------------------------------------------------------
    denom_exceptions: Counter = Counter()
    denom_totals: Counter = Counter()
    if txn_ids:
        cm_rows = (
            session.query(CashMovement.transaction_id, CashMovement.note_info, CashMovement.to_state)
            .filter(CashMovement.transaction_id.in_(txn_ids))
            .all()
        )
        for tid, note_info, to_state in cm_rows:
            info = note_info or {}
            denom = next((info[k] for k in _DENOM_KEYS if info.get(k) is not None), None)
            if denom is None or str(denom).strip().upper() in ("", "UNKNOWN"):
                continue  # uninterpretable denominations carry no pattern signal
            denom_totals[denom] += 1
            if to_state in ("REJECTED", "JAMMED") or to_state not in ("STORED", "RETURNED"):
                denom_exceptions[denom] += 1
    for denom, count in denom_exceptions.most_common():
        if count >= PATTERN_MIN_REPEATS:
            total = denom_totals[denom]
            stats = {"denomination": denom, "count": count, "total_movements": total}
            found.append(
                _pattern_base(
                    "denomination_pattern",
                    f"{count} exception movements on denomination {denom} "
                    f"(of {total} movements with that denomination).",
                    stats,
                    "UNKNOWN",
                )
            )

    # ---- repeated machine failures -----------------------------------------------------
    machine_fail: Counter = Counter()
    for r in rows:
        if r.status in ("FAILED", "INCOMPLETE") and r.machine_id:
            machine_fail[r.machine_id] += 1
    for machine_id, count in machine_fail.most_common(5):
        if count >= PATTERN_MIN_REPEATS:
            stats = {"machine_id": machine_id, "failed_incomplete_count": count}
            found.append(
                _pattern_base(
                    "repeated_machine_failure",
                    f"Machine {machine_id} had {count} FAILED/INCOMPLETE transactions in the window.",
                    stats,
                    "POSSIBLE",
                )
            )

    return {
        "window_days": window_days,
        "patterns": found,
        "thresholds": {
            "min_repeats": PATTERN_MIN_REPEATS,
            "time_share": PATTERN_TIME_SHARE,
            "model_share": PATTERN_MODEL_SHARE,
        },
        "note": (
            "Patterns are advisory observations from history. They never become "
            "production diagnostic rules automatically — see rule-suggestions."
        ),
    }


# --------------------------------------------------------------------------- #
# §3 — cross-machine comparison
# --------------------------------------------------------------------------- #


def _machine_versions(session: Session, machine: Machine) -> list[str]:
    """Extract firmware/software versions from the machine's stored log lines.

    The regexes come from the model package (``detection.version_patterns``);
    models without patterns (or unbound machines) report UNKNOWN. Bounded to
    the first 300 lines per log file, max 10 files.
    """
    patterns: list[re.Pattern] = []
    model_code = machine.machine_model.code if machine.machine_model else None
    if model_code:
        adapter = model_registry.get_model(model_code)
        cfg = getattr(adapter, "model_config", {}) or {}
        vp = (((cfg.get("model") or {}).get("detection")) or {}).get("version_patterns") or []
        for p in vp:
            if isinstance(p, str):
                try:
                    patterns.append(re.compile(p))
                except re.error:
                    continue
    if not patterns:
        return ["UNKNOWN"]

    file_ids = [
        row[0]
        for row in session.query(LogFile.id)
        .filter(LogFile.machine_id == machine.id)
        .limit(10)
        .all()
    ]
    versions: set[str] = set()
    compiled = [re.compile(p) for p in patterns]
    for fid in file_ids:
        lines = (
            session.query(LogLine.raw_text)
            .filter(LogLine.log_file_id == fid, LogLine.line_number <= 300)
            .all()
        )
        for (text,) in lines:
            for c in patterns:
                m = c.search(text or "")
                if m and m.groups():
                    versions.add(m.group(1))
    return sorted(versions) if versions else ["UNKNOWN"]


def cross_machine(session: Session, *, window_days: int = 90) -> dict:
    rows = _txn_window(session, window_days)
    txn_ids = [r.id for r in rows]
    machines = {m.id: m for m in session.query(Machine).all()}

    per_txn: dict[str, dict] = {}
    for r in rows:
        per_txn.setdefault(r.machine_id or "unbound", {"total": 0, "failed": 0, "txns": []})
        agg = per_txn[r.machine_id or "unbound"]
        agg["total"] += 1
        if r.status in ("FAILED", "DECLINED", "INCOMPLETE"):
            agg["failed"] += 1
        agg["txns"].append(r.id)

    findings_by_machine: dict[str, Counter] = defaultdict(Counter)
    if txn_ids:
        q = (
            session.query(
                Transaction.machine_id,
                DiagnosticFinding.rule_id,
                func.count(),
            )
            .join(DiagnosticFinding, DiagnosticFinding.transaction_id == Transaction.id)
            .filter(Transaction.id.in_(txn_ids))
            .group_by(Transaction.machine_id, DiagnosticFinding.rule_id)
            .all()
        )
        for mid, rule_id, count in q:
            findings_by_machine[mid or "unbound"][rule_id] += int(count)

    machines_out = []
    for key, agg in per_txn.items():
        machine = machines.get(key)
        model_code = None
        if machine is not None and machine.machine_model:
            model_code = machine.machine_model.code
        elif key != "unbound":
            model_code = None
        # bound lookups via rows for unbound machines
        if model_code is None:
            for r in rows:
                if (r.machine_id or "unbound") == key and r.model_code:
                    model_code = r.model_code
                    break
        machines_out.append(
            {
                "machine_id": key,
                "serial_number": machine.serial_number if machine else None,
                "location": machine.location if machine else None,
                "model_code": model_code,
                "software_versions": _machine_versions(session, machine) if machine else ["UNKNOWN"],
                "transactions": agg["total"],
                "failures": agg["failed"],
                "failure_rate": round(agg["failed"] / agg["total"], 4) if agg["total"] else 0.0,
                "top_rules": [
                    {"rule_id": k, "count": v}
                    for k, v in findings_by_machine.get(key, Counter()).most_common(5)
                ],
            }
        )
    machines_out.sort(key=lambda m: -m["failure_rate"])

    def group(by: str) -> list[dict]:
        groups: dict[str, dict] = defaultdict(lambda: {"machines": 0, "transactions": 0, "failures": 0})
        for m in machines_out:
            key = m.get(by) or "UNKNOWN"
            if isinstance(key, list):
                key = ", ".join(key)
            g = groups[key]
            g["machines"] += 1
            g["transactions"] += m["transactions"]
            g["failures"] += m["failures"]
        return [
            {
                by: k,
                **v,
                "failure_rate": round(v["failures"] / v["transactions"], 4) if v["transactions"] else 0.0,
            }
            for k, v in sorted(groups.items())
        ]

    return {
        "window_days": window_days,
        "machines": machines_out,
        "by_location": group("location"),
        "by_model": group("model_code"),
        "by_software_version": group("software_versions"),
        "note": (
            "software_versions are extracted with the model package's "
            "detection.version_patterns (SYNTHETIC patterns; UNKNOWN where no "
            "pattern is configured). Comparison is descriptive — not a verdict."
        ),
    }


# --------------------------------------------------------------------------- #
# §6 — maintenance insights (WATCH / WARNING / HIGH_RISK)
# --------------------------------------------------------------------------- #

_FLAG_THRESHOLDS = {
    # component rate within the recent window (per transaction)
    "rate_high": 0.30,   # HIGH_RISK also requires this absolute rate
    "increase_warning": 1.5,   # recent >= 1.5× baseline
    "increase_watch": 1.1,     # recent > 1.1× baseline
    "min_baseline": 4,         # need some history before flagging
}

_METRICS = ("jam_frequency", "hardware_error_rate", "failure_rate", "sensor_abnormality_rate")


def maintenance(session: Session, *, recent_days: int = 7, baseline_days: int = 30) -> dict:
    """Per-machine increasing-metric detection with WATCH/WARNING/HIGH_RISK flags.

    The flags are prioritisation heuristics on aggregate rates — they never
    declare component failure and never replace the per-transaction
    diagnosis.
    """
    now = datetime.utcnow()
    baseline_start = now - timedelta(days=baseline_days)
    recent_start = now - timedelta(days=recent_days)

    machines = session.query(Machine).all()
    out = []
    for machine in machines:
        rows = (
            session.query(
                Transaction.id, Transaction.start_time, Transaction.status
            )
            .filter(
                Transaction.machine_id == machine.id,
                or_(Transaction.start_time.is_(None), Transaction.start_time >= baseline_start),
            )
            .all()
        )
        baseline_rows = [r for r in rows if r.start_time and r.start_time < recent_start]
        recent_rows = [r for r in rows if r.start_time is None or r.start_time >= recent_start]

        def rates(txn_rows) -> dict:
            ids = [r.id for r in txn_rows]
            total = len(txn_rows)
            failed = sum(1 for r in txn_rows if r.status in ("FAILED", "INCOMPLETE"))
            jams = hw = 0
            sensor_abn = 0
            if ids:
                jams = int(
                    session.query(func.count(DiagnosticFinding.id))
                    .filter(DiagnosticFinding.transaction_id.in_(ids))
                    .filter(DiagnosticFinding.rule_id.in_(("POSSIBLE_CASH_JAM", "CONFIRMED_CASH_JAM")))
                    .scalar()
                    or 0
                )
                hw = int(
                    session.query(func.count(DiagnosticFinding.id))
                    .filter(DiagnosticFinding.transaction_id.in_(ids))
                    .filter(DiagnosticFinding.diagnosis_class == "HARDWARE_FAILURE")
                    .scalar()
                    or 0
                )
                sensor_abn = int(
                    session.query(func.count(SensorEvent.id))
                    .filter(SensorEvent.transaction_id.in_(ids))
                    .filter(SensorEvent.abnormal_duration_ms.isnot(None))
                    .scalar()
                    or 0
                )
            div = max(total, 1)
            return {
                "jam_frequency": round(jams / div, 4),
                "hardware_error_rate": round(hw / div, 4),
                "failure_rate": round(failed / div, 4),
                "sensor_abnormality_rate": round(sensor_abn / div, 4),
                "_total": total,
            }

        baseline = rates(baseline_rows)
        recent = rates(recent_rows)

        metrics = {}
        overall_label = "WATCH"
        worst = 0
        for metric in _METRICS:
            b = baseline[metric]
            r = recent[metric]
            ratio = round(r / b, 2) if b > 0 else (None if r == 0 else 99.99)
            if b == 0 and r == 0:
                label = "WATCH"
            elif ratio is not None and ratio >= _FLAG_THRESHOLDS["increase_warning"] and r >= _FLAG_THRESHOLDS["rate_high"]:
                label = "HIGH_RISK"
            elif ratio is not None and ratio >= _FLAG_THRESHOLDS["increase_warning"]:
                label = "WARNING"
            elif ratio is not None and ratio > _FLAG_THRESHOLDS["increase_watch"]:
                label = "WATCH"
            else:
                # high-but-not-increasing rates stay WATCH: the spec flags
                # machines showing *increasing* problems; (b==0, r>0) already
                # escalates through ratio=99.99 above
                label = "WATCH"
            metrics[metric] = {"baseline": b, "recent": r, "ratio": ratio, "flag": label}
            order = {"WATCH": 0, "WARNING": 1, "HIGH_RISK": 2}
            if order[label] > worst:
                worst = order[label]
        overall = ["WATCH", "WARNING", "HIGH_RISK"][worst]
        # machines with almost no baseline history are not escalatable
        if baseline["_total"] < _FLAG_THRESHOLDS["min_baseline"]:
            overall = "WATCH"

        model_code = machine.machine_model.code if machine.machine_model else None
        out.append(
            {
                "machine_id": machine.id,
                "serial_number": machine.serial_number,
                "name": machine.name,
                "location": machine.location,
                "model_code": model_code,
                "baseline_days": baseline_days,
                "recent_days": recent_days,
                "baseline_transactions": baseline["_total"],
                "recent_transactions": recent["_total"],
                "metrics": metrics,
                "overall_flag": overall,
            }
        )

    out.sort(key=lambda m: {"HIGH_RISK": 0, "WARNING": 1, "WATCH": 2}[m["overall_flag"]])
    return {
        "recent_days": recent_days,
        "baseline_days": baseline_days,
        "machines": out,
        "thresholds": _FLAG_THRESHOLDS,
        "note": (
            "Flags are aggregate-rate heuristics for triage prioritisation. "
            "They are NOT diagnoses and never declare component failure — open the "
            "transactions for the evidence-based analysis."
        ),
    }


# --------------------------------------------------------------------------- #
# §9 — completion questions, answered directly
# --------------------------------------------------------------------------- #


def insights(session: Session, *, window_days: int = 90) -> dict:
    rows = _txn_window(session, window_days)
    txn_ids = [r.id for r in rows]
    by_machine: Counter = Counter()
    machine_model: dict[str, str | None] = {}
    for r in rows:
        if r.machine_id:
            by_machine[r.machine_id] += 1 if r.status in ("FAILED", "DECLINED", "INCOMPLETE") else 0
            if r.machine_id not in machine_model:
                m = session.query(Machine).filter(Machine.id == r.machine_id).first()
                machine_model[r.machine_id] = m.machine_model.code if m and m.machine_model else None

    # model failure rates
    model_tot: Counter = Counter()
    model_fail: Counter = Counter()
    for r in rows:
        mc = r.model_code or "UNKNOWN"
        model_tot[mc] += 1
        if r.status in ("FAILED", "DECLINED", "INCOMPLETE"):
            model_fail[mc] += 1

    # errors increasing: compare second half of window vs first half
    mid = _cutoff(window_days // 2)
    err_first: Counter = Counter()
    err_second: Counter = Counter()
    if txn_ids:
        q = (
            session.query(
                Transaction.start_time, TransactionEvent.detail
            )
            .join(TransactionEvent, TransactionEvent.transaction_id == Transaction.id)
            .filter(Transaction.id.in_(txn_ids))
            .filter(TransactionEvent.event_code.in_(_ERROR_EVENTS))
            .all()
        )
        for ts, detail in q:
            code = (detail or {}).get("error_code") or "UNKNOWN"
            if ts and ts >= mid:
                err_second[code] += 1
            else:
                err_first[code] += 1
    increasing = [
        {"error_code": code, "first_half": err_first[code], "second_half": err_second[code]}
        for code in err_second
        if err_second[code] > err_first[code]
    ]
    increasing.sort(key=lambda e: -(e["second_half"] - e["first_half"]))

    # faults preceding transaction failure (same-transaction neighbor analysis)
    preceding = Counter()
    if txn_ids:
        events = (
            session.query(
                TransactionEvent.transaction_id,
                TransactionEvent.event_code,
                TransactionEvent.seq,
            )
            .filter(TransactionEvent.transaction_id.in_(txn_ids))
            .order_by(TransactionEvent.transaction_id, TransactionEvent.seq)
            .all()
        )
        failed_ids = {r.id for r in rows if r.status in ("FAILED", "INCOMPLETE")}
        by_txn: dict[str, list[str]] = defaultdict(list)
        for tid, code, _seq in events:
            by_txn[tid].append(code)
        for tid in failed_ids:
            codes = by_txn.get(tid) or []
            for idx, code in enumerate(codes):
                if code in _JAM_EVENTS or code in _ERROR_EVENTS or code == _DEVICE_UNAVAILABLE:
                    if idx > 0:
                        preceding[codes[idx - 1]] += 1

    problems_ranked = sorted(by_machine.items(), key=lambda kv: -kv[1])
    worst_model = max(
        ((mc, model_fail[mc] / tot) for mc, tot in model_tot.items() if tot >= 1),
        key=lambda kv: kv[1],
        default=(None, None),
    )

    return {
        "window_days": window_days,
        "machines_with_most_problems": [
            {"machine_id": mid_, "failures": count, "model_code": machine_model.get(mid_)}
            for mid_, count in problems_ranked[:5]
        ],
        "errors_increasing": increasing[:5],
        "model_highest_failure_rate": (
            {"model_code": worst_model[0], "failure_rate": round(worst_model[1], 4)}
            if worst_model[0]
            else None
        ),
        "faults_preceding_failure": [
            {"event": code, "count": count} for code, count in preceding.most_common(5)
        ],
        "machines_to_investigate_first": [
            m["machine_id"]
            for m in maintenance(session, recent_days=min(30, window_days), baseline_days=max(window_days, 30))["machines"]
            if m["overall_flag"] == "HIGH_RISK"
        ][:5]
        or [
            mid_
            for mid_, _ in problems_ranked[:3]
        ],
        "note": "Direct answers over the analysis window — every number traces to stored evidence.",
    }
