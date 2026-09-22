"""Phase 5: evidence-driven diagnostic engine (rules → findings).

Consumes the picture assembled by Phases 2–4 for ONE transaction —
normalized events, cash lifecycle movements, hardware records (sensors,
motors, gates/shutters, transports), jam classifications — and evaluates
data-driven diagnostic rules into structured FINDINGS:

    finding_id, category, severity, confidence, summary,
    interpretation, possible_causes, recommended_action, evidence

Non-negotiable rules:
* **Rules are data.** The engine has no model-specific or hard-coded
  diagnostic logic; rules/requirements/reconciliation live in
  ``config/diagnostics/rules.yaml`` plus optional per-model
  ``diagnostics.yaml`` overlays.
* **Evidence or it didn't happen.** Every finding references the actual
  normalized events, raw lines (file id + line number + raw text),
  timestamps, devices, cash states — findings without evidence are never
  produced.
* **Confidence is not certainty.** Levels are LOW / MODERATE / HIGH /
  VERY_HIGH, derived from the rule's base and how many *independent*
  evidence sources corroborate it.
* **No unsupported conclusions.** Summaries/interpretations state observed
  facts and hedged hypotheses; possible_causes are hypotheses, never
  component-level root causes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core.model_config import config_root, load_model_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

# Root cause categories (section 2).
CATEGORIES: tuple[str, ...] = (
    "HARDWARE",
    "SOFTWARE",
    "FIRMWARE",
    "CONFIGURATION",
    "HOST",
    "NETWORK",
    "COMMUNICATION",
    "SENSOR",
    "MOTOR",
    "GATE",
    "SHUTTER",
    "TRANSPORT",
    "CASH_HANDLING",
    "UNKNOWN",
)

# Failure classes the engine distinguishes (section 7) + report classes.
DIAGNOSIS_CLASSES: tuple[str, ...] = (
    "HOST_FAILURE",
    "HARDWARE_FAILURE",
    "COMMUNICATION_FAILURE",
    "APPLICATION_FAILURE",
    "CASH_EXCEPTION",
    "REQUIREMENT_VIOLATION",
    "NO_FAILURE",
    "INSUFFICIENT_DATA",
)

SEVERITIES: tuple[str, ...] = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
CONFIDENCE_LEVELS: tuple[str, ...] = ("LOW", "MODERATE", "HIGH", "VERY_HIGH")

_RECONCILIATION_ISSUES: tuple[str, ...] = (
    "ACCEPTED_NOT_STORED",
    "ACCEPTED_NOT_RETURNED",
    "AMOUNT_MISMATCH",
    "COUNT_MISMATCH",
    "HOST_MISMATCH",
    "TRANSACTION_MISMATCH",
)

_CONTROL_KEYS = {"all", "any", "exclude"}


def _sev_index(sev: str) -> int:
    return SEVERITIES.index(sev) if sev in SEVERITIES else 0


def _conf_index(conf: str) -> int:
    return CONFIDENCE_LEVELS.index(conf) if conf in CONFIDENCE_LEVELS else 0


def _bump_confidence(conf: str, steps: int) -> str:
    return CONFIDENCE_LEVELS[min(len(CONFIDENCE_LEVELS) - 1, _conf_index(conf) + max(0, steps))]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class Rule:
    id: str
    category: str | None = None
    diagnosis_class: str = "UNKNOWN"
    severity: str = "MEDIUM"
    confidence_base: str = "LOW"
    summary: str = ""
    interpretation: str = ""
    possible_causes: list[str] = field(default_factory=list)
    recommended_action: str = ""
    conditions: dict = field(default_factory=dict)
    enabled: bool = True


@dataclass
class Requirement:
    id: str
    description: str
    violation_summary: str = ""
    category: str = "UNKNOWN"
    severity: str = "HIGH"
    trigger: dict = field(default_factory=dict)
    violation: dict = field(default_factory=dict)
    enabled: bool = True


@dataclass
class DiagnosticConfig:
    rules: list[Rule] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    reconciliation: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    @staticmethod
    def _universal_path():
        return config_root().parent / "diagnostics" / "rules.yaml"

    @classmethod
    def load(cls, model_code: str | None = None) -> "DiagnosticConfig":
        import yaml

        universal: dict = {}
        path = cls._universal_path()
        if path.exists():
            try:
                universal = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                logger.error("Invalid universal diagnostics YAML", extra={"error": str(exc)})

        model_cfg: dict = {}
        if model_code:
            model_cfg = (load_model_config(model_code) or {}).get("diagnostics") or {}

        cfg = cls()
        by_id: dict[str, Rule] = {}
        for raw in (universal or {}).get("rules") or []:
            rule = cls._rule_from(raw)
            if rule:
                by_id[rule.id] = rule
        # Model overlay: same id replaces (keeps position), new id appends.
        for raw in (model_cfg or {}).get("rules") or []:
            rule = cls._rule_from(raw)
            if not rule:
                continue
            if rule.id in by_id:
                by_id[rule.id] = rule
            else:
                by_id[rule.id] = rule

        req_by_id: dict[str, Requirement] = {}
        for raw in (universal or {}).get("requirements") or []:
            req = cls._requirement_from(raw)
            if req:
                req_by_id[req.id] = req
        for raw in (model_cfg or {}).get("requirements") or []:
            req = cls._requirement_from(raw)
            if req:
                req_by_id[req.id] = req

        cfg.rules = [r for r in by_id.values() if r.enabled]
        cfg.requirements = [r for r in req_by_id.values() if r.enabled]
        universal_rc = (universal or {}).get("reconciliation") or {}
        model_rc = (model_cfg or {}).get("reconciliation") or {}
        reconciliation = dict(universal_rc)
        for key, value in model_rc.items():
            if isinstance(value, dict) and isinstance(reconciliation.get(key), dict):
                merged = dict(reconciliation[key])
                merged.update(value)
                reconciliation[key] = merged
            else:
                reconciliation[key] = value
        cfg.reconciliation = reconciliation
        return cfg

    @staticmethod
    def _rule_from(raw: dict) -> Rule | None:
        if not isinstance(raw, dict) or not raw.get("id"):
            return None
        return Rule(
            id=str(raw["id"]),
            category=raw.get("category"),
            diagnosis_class=str(raw.get("diagnosis_class", "UNKNOWN")),
            severity=str(raw.get("severity", "MEDIUM")),
            confidence_base=str(raw.get("confidence_base", "LOW")),
            summary=str(raw.get("summary", "")),
            interpretation=str(raw.get("interpretation", "")),
            possible_causes=[str(c) for c in (raw.get("possible_causes") or [])],
            recommended_action=str(raw.get("recommended_action", "")),
            conditions=dict(raw.get("conditions") or _split_conditions(raw)),
            enabled=bool(raw.get("enabled", True)),
        )

    @staticmethod
    def _requirement_from(raw: dict) -> Requirement | None:
        if not isinstance(raw, dict) or not raw.get("id"):
            return None
        return Requirement(
            id=str(raw["id"]),
            description=str(raw.get("description", "")),
            violation_summary=str(raw.get("violation_summary", "")),
            category=str(raw.get("category", "UNKNOWN")),
            severity=str(raw.get("severity", "HIGH")),
            trigger=dict(raw.get("trigger") or {}),
            violation=dict(raw.get("violation") or {}),
            enabled=bool(raw.get("enabled", True)),
        )


def _split_conditions(raw: dict) -> dict:
    """Rules may write conditions at the top level; collect operators into
    an ``all`` group, explicit all/any/exclude keys stay as-is."""
    conditions: dict = {}
    alls: list = []
    for key, value in raw.items():
        if key in {"id", "category", "diagnosis_class", "severity", "confidence_base",
                   "summary", "interpretation", "possible_causes", "recommended_action",
                   "enabled", "conditions"}:
            continue
        if key == "all":
            conditions["all"] = value
        elif key == "any":
            conditions["any"] = value
        elif key == "exclude":
            conditions["exclude"] = value
        else:
            alls.append({key: value})
    if alls:
        conditions.setdefault("all", [])
        if isinstance(conditions["all"], list):
            conditions["all"] = alls + conditions["all"]
    return conditions


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class DiagnosisContext:
    """Everything the engine may look at for ONE transaction.

    Attribute names match both ORM rows (``TransactionEvent``,
    ``CashMovement``, ``SensorEvent`` …) and the SimpleNamespace fakes used
    in unit tests — the engine itself never touches the database.
    """

    transaction_id: str
    model_code: str | None
    status: str | None
    events: list = field(default_factory=list)  # ordered, this transaction
    cash_movements: list = field(default_factory=list)  # ordered
    final_cash_state: str | None = None
    sensors: list = field(default_factory=list)
    motors: list = field(default_factory=list)
    gates: list = field(default_factory=list)  # gate|shutter rows
    transports: list = field(default_factory=list)
    faults: list = field(default_factory=list)  # Phase 4 FaultAssessment rows
    # Events of SUBSEQUENT transactions (same upload) — used only by the
    # requirement engine to observe (automatic) recovery after this txn.
    subsequent_events: list = field(default_factory=list)
    reconciliation: list = field(default_factory=list)  # computed at evaluate()

    @property
    def cash_states(self) -> list[str]:
        return [m.to_state for m in self.cash_movements]

    def host_state(self) -> str:
        codes = {getattr(e, "event_code", "") for e in self.events}
        if "HOST_DECLINED" in codes:
            return "DECLINED"
        if "HOST_RESPONSE" in codes:
            return "APPROVED"
        if "HOST_REQUEST" in codes:
            return "NO_RESPONSE"
        return "NO_REQUEST"

    def cash_state_reached(self, states) -> bool:
        return any(s in states for s in self.cash_states)


# ---------------------------------------------------------------------------
# Evidence refs (section 4)
# ---------------------------------------------------------------------------


def _ts(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _ev_event(e, kind: str = "event", **extra) -> dict:
    ref = {
        "kind": kind,
        "event": getattr(e, "event_code", ""),
        "timestamp": _ts(getattr(e, "timestamp", None)),
        "device": getattr(e, "device", None),
        "file_id": getattr(e, "log_file_id", None),
        "line_number": getattr(e, "line_number", None),
        "raw_text": (getattr(e, "raw_text", "") or "")[:400],
    }
    ref.update(extra)
    return ref


def _ev_cash(m) -> dict:
    return {
        "kind": "cash",
        "transition": f"{m.from_state}->{m.to_state}",
        "evidence_event": m.evidence_event,
        "timestamp": _ts(m.timestamp),
        "device": m.device,
        "file_id": m.log_file_id,
        "line_number": m.line_number,
        "raw_text": (m.raw_text or "")[:400],
    }


def _ev_sensor(s) -> dict:
    return {
        "kind": "sensor",
        "sensor": s.sensor,
        "previous_state": s.previous_state,
        "new_state": s.new_state,
        "expected_state": s.expected_state,
        "actual_state": s.actual_state,
        "abnormal_duration_ms": s.abnormal_duration_ms,
        "timestamp": _ts(s.timestamp),
        "device": s.device,
        "file_id": s.log_file_id,
        "line_number": s.line_number,
        "raw_text": (s.raw_text or "")[:400],
    }


def _ev_motor(m) -> dict:
    return {
        "kind": "motor",
        "motor": m.motor,
        "started_at": _ts(m.started_at),
        "stopped_at": _ts(m.stopped_at),
        "duration_ms": m.duration_ms,
        "timeout_ms": m.timeout_ms,
        "timed_out": m.timed_out,
        "file_id": m.log_file_id,
        "line_number": m.line_number,
        "raw_text": (m.raw_text or "")[:400],
    }


def _ev_transport(t) -> dict:
    return {
        "kind": "transport",
        "name": t.name,
        "outcome": t.outcome,
        "started_at": _ts(t.started_at),
        "ended_at": _ts(t.ended_at),
        "file_id": t.log_file_id,
        "line_number": t.line_number,
        "raw_text": (t.raw_text or "")[:400],
    }


def _ev_gate(g) -> dict:
    return {
        "kind": g.kind,
        "name": g.name,
        "command": g.command,
        "expected_state": g.expected_state,
        "actual_state": g.actual_state,
        "timed_out": g.timed_out,
        "state_mismatch": g.state_mismatch,
        "file_id": g.log_file_id,
        "line_number": g.line_number,
        "raw_text": (g.raw_text or "")[:400],
    }


def _ev_fault(f) -> dict:
    refs = getattr(f, "evidence", None) or []
    primary_ts = next(
        (
            r.get("timestamp")
            for r in refs
            if isinstance(r, dict) and r.get("timestamp")
        ),
        None,
    )
    return {
        "kind": "fault",
        "classification": f.classification,
        "subject_kind": f.subject_kind,
        "subject_name": f.subject_name,
        "statement": f.statement,
        "timestamp": primary_ts,
    }


# ---------------------------------------------------------------------------
# Findings & report
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    finding_id: str
    rule_id: str
    diagnosis_class: str
    category: str | None
    severity: str
    confidence: str
    summary: str
    interpretation: str
    possible_causes: list[str]
    recommended_action: str
    evidence: list[dict] = field(default_factory=list)
    cash_states: list[str] = field(default_factory=list)


@dataclass
class ReconciliationIssue:
    name: str
    detail: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)


@dataclass
class DiagnosticReport:
    transaction_id: str
    summary: str
    classification: str
    diagnosis_class: str
    severity: str
    confidence: str
    final_cash_state: str | None
    findings: list[Finding] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class DiagnosticEngine:
    """Evaluates data-driven rules against a :class:`DiagnosisContext`."""

    def __init__(self, config: DiagnosticConfig) -> None:
        self.cfg = config

    # -- public ---------------------------------------------------------------

    def evaluate(self, ctx: DiagnosisContext) -> DiagnosticReport:
        ctx.reconciliation = self._reconcile(ctx)
        findings: list[Finding] = []
        for rule in self.cfg.rules:
            evidence = self._evaluate_rule(rule, ctx)
            if evidence is None:
                continue
            findings.append(self._finding_from_rule(rule, evidence, ctx))
        for req in self.cfg.requirements:
            finding = self._evaluate_requirement(req, ctx)
            if finding is not None:
                findings.append(finding)

        order = {f.rule_id: i for i, f in enumerate(findings)}
        findings.sort(key=lambda f: (-_sev_index(f.severity), list(order).index(f.rule_id)))

        if findings:
            top = findings[0]
            classification = top.rule_id
            diagnosis_class = top.diagnosis_class
            severity = top.severity
            confidence = top.confidence
            summary = (
                f"{len(findings)} finding(s); primary: {top.rule_id} "
                f"[{top.diagnosis_class}, severity {top.severity}, confidence {top.confidence}]"
                + (f"; final cash state {ctx.final_cash_state}" if ctx.final_cash_state else "")
            )
        else:
            classification, diagnosis_class = "NO_FAILURE", "NO_FAILURE"
            severity, confidence = "INFO", "LOW"
            summary = "No diagnostic rules matched this transaction."

        return DiagnosticReport(
            transaction_id=ctx.transaction_id,
            summary=summary,
            classification=classification,
            diagnosis_class=diagnosis_class,
            severity=severity,
            confidence=confidence,
            final_cash_state=ctx.final_cash_state,
            findings=findings,
        )

    # -- rule evaluation ---------------------------------------------------------

    def _evaluate_rule(self, rule: Rule, ctx: DiagnosisContext) -> list[dict] | None:
        matcher = _Matcher(ctx)
        conditions = rule.conditions
        alls = conditions.get("all")
        if alls is None and not ({"any", "exclude"} & set(conditions)):
            alls = []
        evidence: list[dict] = []
        if alls is not None:
            ok, evidence = matcher.match_group({"all": alls})
            if not ok:
                return None
        if "any" in conditions and conditions["any"] is not None:
            ok, ev_any = matcher.match_group({"any": conditions["any"]})
            if not ok:
                return None
            evidence += ev_any
        if "exclude" in conditions and conditions["exclude"]:
            ok, _ = matcher.match_group({"any": conditions["exclude"]})
            if ok:
                return None
        return evidence

    def _finding_from_rule(self, rule: Rule, evidence: list[dict], ctx: DiagnosisContext) -> Finding:
        steps = _confidence_steps(_evidence_kinds(evidence))
        return Finding(
            finding_id=rule.id,
            rule_id=rule.id,
            diagnosis_class=rule.diagnosis_class,
            category=rule.category,
            severity=rule.severity,
            confidence=_bump_confidence(rule.confidence_base, steps),
            summary=rule.summary,
            interpretation=rule.interpretation,
            possible_causes=list(rule.possible_causes),
            recommended_action=rule.recommended_action,
            evidence=evidence,
            cash_states=list(ctx.cash_states),
        )

    # -- requirement evaluation ----------------------------------------------------

    def _evaluate_requirement(self, req: Requirement, ctx: DiagnosisContext) -> Finding | None:
        matcher = _Matcher(ctx)
        ok, trigger_ev = matcher.match_group(req.trigger)
        if not ok:
            return None
        anchor = next(
            (
                _parse_iso(e.get("timestamp"))
                for e in trigger_ev
                if e.get("timestamp")
            ),
            None,
        )
        if anchor is None and ctx.events:
            # Trigger refs without their own timestamp (e.g. a Phase 4 fault
            # classification): anchor recovery detection at the LAST event
            # log-time of this transaction — never at analysis wall-clock.
            anchor = next(
                (e.timestamp for e in reversed(ctx.events) if e.timestamp is not None),
                None,
            )
        if anchor is None:
            return None
        ok_v, viol_ev = matcher.match_group(req.violation, after=anchor)
        if not ok_v:
            return None
        evidence = list(trigger_ev) + list(viol_ev)
        steps = _confidence_steps(_evidence_kinds(evidence))
        return Finding(
            finding_id=req.id,
            rule_id=req.id,
            diagnosis_class="REQUIREMENT_VIOLATION",
            category=req.category,
            severity=req.severity,
            confidence=_bump_confidence("MODERATE", steps),
            summary=f"REQUIREMENT_VIOLATION: {req.id}",
            interpretation=(
                f"Configured requirement: {req.description.strip()} — {req.violation_summary.strip()} "
                "This finding is produced only because the requirement is configured; it is an "
                "operational-compliance observation, not a hardware diagnosis."
            ),
            possible_causes=[
                "automatic recovery not blocked by the application",
                "manual intervention performed but not recorded in the logs",
            ],
            recommended_action=(
                "Review the recovery timeline below against the operating procedure; "
                "if recovery was automatic, investigate why the machine left the jammed "
                "state without recorded intervention."
            ),
            evidence=evidence,
            cash_states=list(ctx.cash_states),
        )

    # -- reconciliation (section 8) -------------------------------------------------

    def _reconcile(self, ctx: DiagnosisContext) -> list[ReconciliationIssue]:
        issues: list[ReconciliationIssue] = []
        reached = ctx.cash_states
        pre_terminal = ("ACCEPTED", "ESCROW", "COUNTED", "VALIDATED", "CONFIRMED", "TRANSPORTING")
        host_declined = ctx.host_state() == "DECLINED"
        status_failed = ctx.status in ("FAILED", "DECLINED")
        returned = any(getattr(e, "event_code", "") in ("CASH_RETURNED", "CASH_REJECTED") for e in ctx.events)

        if any(s in pre_terminal for s in reached) and ctx.final_cash_state == "UNKNOWN_LOCATION":
            ev = [_ev_cash(m) for m in ctx.cash_movements]
            issues.append(
                ReconciliationIssue(
                    "ACCEPTED_NOT_STORED",
                    {"final_cash_state": ctx.final_cash_state, "reached": reached},
                    ev,
                )
            )
            if (host_declined or status_failed) and not returned:
                issues.append(
                    ReconciliationIssue(
                        "ACCEPTED_NOT_RETURNED",
                        {"host_state": ctx.host_state(), "status": ctx.status},
                        ev,
                    )
                )

        checks = (self.cfg.reconciliation or {}).get("checks") or {}
        pairs = (self.cfg.reconciliation or {}).get("pairs") or []
        tolerance = float((self.cfg.reconciliation or {}).get("tolerance", 0.01))
        values: dict[str, tuple[Any, list[dict]] | None] = {}
        for name, spec in checks.items():
            values[name] = self._scan_value(ctx, spec)
        for pair in pairs:
            names = pair.get("compare") or []
            issue = pair.get("issue")
            if len(names) != 2 or not issue:
                continue
            left, right = values.get(names[0]), values.get(names[1])
            if not left or not right:
                continue  # a missing side is never a mismatch — never invent
            (lv, lev), (rv, rev) = left, right
            differs = (
                abs(float(lv) - float(rv)) > tolerance
                if isinstance(lv, (int, float)) and isinstance(rv, (int, float))
                else str(lv) != str(rv)
            )
            if differs:
                issues.append(
                    ReconciliationIssue(
                        issue,
                        {names[0]: lv, names[1]: rv, "tolerance": tolerance},
                        lev + rev,
                    )
                )
        return issues

    @staticmethod
    def _scan_value(ctx: DiagnosisContext, spec: dict) -> tuple[Any, list[dict]] | None:
        """First configured-pattern value found on matching events."""
        if not isinstance(spec, dict) or not spec.get("pattern"):
            return None
        wanted = spec.get("events") or []
        try:
            pattern = re.compile(spec["pattern"], re.IGNORECASE)
        except re.error:
            return None
        value_type = str(spec.get("type", "str"))
        for e in ctx.events:
            if getattr(e, "event_code", "") not in wanted:
                continue
            m = pattern.search(getattr(e, "raw_text", "") or "")
            if not m:
                continue
            raw_value = m.group(1) if m.groups() else m.group(0)
            try:
                value = float(raw_value) if value_type == "float" else (
                    int(raw_value) if value_type == "int" else str(raw_value)
                )
            except (TypeError, ValueError):
                continue
            return value, [_ev_event(e)]
        return None


# Canonical evidence source kinds; flattened Phase 4 fault refs
# (jam_indication, transport_timeout, …) all belong to the FAULT source and
# must not inflate the independent-source count used for confidence.
_CANONICAL_KINDS = {
    "event", "cash", "sensor", "motor", "gate", "shutter", "transport",
    "fault", "reconciliation",
}


def _evidence_kinds(evidence: list[dict]) -> set[str]:
    kinds: set[str] = set()
    for e in evidence or []:
        if not isinstance(e, dict):
            continue
        kind = e.get("kind")
        kinds.add(kind if kind in _CANONICAL_KINDS else "fault")
    return kinds


def _confidence_steps(kinds: set[str]) -> int:
    steps = 1 if len(kinds) >= 3 else 0
    steps += 1 if len(kinds) >= 5 else 0
    return steps


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Condition matcher (all operators are data)
# ---------------------------------------------------------------------------


class _Matcher:
    def __init__(self, ctx: DiagnosisContext) -> None:
        self.ctx = ctx

    # -- group evaluation ------------------------------------------------------

    def match_group(self, group: Any, after: datetime | None = None) -> tuple[bool, list[dict]]:
        """Evaluate a condition group. Returns (matched, evidence)."""
        if isinstance(group, list):
            evidence: list[dict] = []
            for item in group:
                ok, ev = self.match_group(item, after=after)
                if not ok:
                    return False, []
                evidence += ev
            return True, evidence
        if not isinstance(group, dict) or not group:
            return False, []
        if "all" in group:
            return self.match_group(group["all"], after=after)
        if "any" in group:
            for item in group["any"] or []:
                ok, ev = self.match_group(item, after=after)
                if ok:
                    return True, ev
            return False, []
        op = next((k for k in group if k not in _CONTROL_KEYS), None)
        if op is None:
            return False, []
        handler = getattr(self, f"_op_{op}", None)
        if handler is None:
            logger.debug("Unknown diagnostic operator ignored", extra={"operator": op})
            return False, []
        if op == "sequence":
            return self._op_sequence(group[op], after=after, window=group.get("window_seconds"))
        if op == "any_event":
            return self._op_any_event(group[op], after=after, within=group.get("within_seconds"))
        return handler(group[op], after=after)

    # -- operators ---------------------------------------------------------------

    def _op_event(self, codes, after=None):
        codes = _as_list(codes)
        hits = [e for e in self.ctx.events if getattr(e, "event_code", "") in codes]
        if after is not None:
            hits = [e for e in hits if e.timestamp and e.timestamp > after]
        return (True, [_ev_event(e) for e in hits[:8]]) if hits else (False, [])

    def _op_any_event(self, codes, after=None, within=None):
        """Events here or in subsequent transactions (requirement recovery)."""
        codes = _as_list(codes)
        hits = [
            e
            for e in list(self.ctx.events) + list(self.ctx.subsequent_events)
            if getattr(e, "event_code", "") in codes
        ]
        if after is not None:
            hits = [e for e in hits if e.timestamp and e.timestamp > after]
            if within is not None:
                limit = after + timedelta(seconds=int(within))
                hits = [e for e in hits if e.timestamp <= limit]
        return (True, [_ev_event(e) for e in hits[:8]]) if hits else (False, [])

    def _op_sequence(self, items, after=None, window=None):
        if isinstance(items, dict):
            window = items.get("window_seconds")
            items = items.get("steps") or []
        events = self.ctx.events
        pos = 0
        matched: list = []
        for item in items:
            codes = _as_list(item.get("event")) if isinstance(item, dict) else _as_list(item)
            device = item.get("device") if isinstance(item, dict) else None
            found = None
            while pos < len(events):
                e = events[pos]
                pos += 1
                if getattr(e, "event_code", "") in codes and (device is None or e.device == device):
                    found = e
                    break
            if found is None:
                return False, []
            if (
                matched
                and window is not None
                and matched[-1].timestamp is not None
                and found.timestamp is not None
                and (found.timestamp - matched[-1].timestamp) > timedelta(seconds=window)
            ):
                return False, []
            matched.append(found)
        return (True, [_ev_event(e) for e in matched]) if matched else (False, [])

    def _op_device(self, name, after=None):
        hits = [e for e in self.ctx.events if e.device == name]
        return (True, [_ev_event(e) for e in hits[:8]]) if hits else (False, [])

    def _op_sensor_anomaly(self, _flag, after=None):
        hits = [
            s
            for s in self.ctx.sensors
            if (s.expected_state and s.actual_state and s.expected_state != s.actual_state)
            or (s.abnormal_duration_ms or 0) > 0
        ]
        return (True, [_ev_sensor(s) for s in hits[:8]]) if hits else (False, [])

    def _op_motor_timeout(self, name=None, after=None):
        hits = [
            m
            for m in self.ctx.motors
            if m.timed_out and (name in (None, True, False) or getattr(m, "motor", "") == name)
        ]
        return (True, [_ev_motor(m) for m in hits[:8]]) if hits else (False, [])

    def _op_gate_anomaly(self, _flag, after=None):
        hits = [
            g
            for g in self.ctx.gates
            if g.kind == "gate" and (g.state_mismatch or g.timed_out)
        ]
        return (True, [_ev_gate(g) for g in hits[:8]]) if hits else (False, [])

    def _op_shutter_anomaly(self, _flag, after=None):
        hits = [
            g
            for g in self.ctx.gates
            if g.kind == "shutter" and (g.state_mismatch or g.timed_out)
        ]
        return (True, [_ev_gate(g) for g in hits[:8]]) if hits else (False, [])

    def _op_transport_outcome(self, outcomes, after=None):
        outcomes = _as_list(outcomes)
        hits = [t for t in self.ctx.transports if t.outcome in outcomes]
        return (True, [_ev_transport(t) for t in hits[:8]]) if hits else (False, [])

    def _op_jam_classification(self, classifications, after=None):
        classifications = _as_list(classifications)
        hits = [f for f in self.ctx.faults if f.classification in classifications]
        if not hits:
            return False, []
        evidence = [_ev_fault(f) for f in hits[:4]]
        for f in hits[:4]:
            # Flatten the Phase 4 assessment's own evidence (raw-line refs)
            # so the finding cites the actual events, not just the label.
            for ref in (getattr(f, "evidence", None) or [])[:6]:
                if isinstance(ref, dict) and ref.get("kind") and ref not in evidence:
                    evidence.append(ref)
        return True, evidence

    def _op_cash_state(self, states, after=None):
        states = _as_list(states)
        hits = [m for m in self.ctx.cash_movements if m.to_state in states]
        return (True, [_ev_cash(m) for m in hits[:8]]) if hits else (False, [])

    def _op_cash_final_state(self, states, after=None):
        states = _as_list(states)
        if self.ctx.final_cash_state in states:
            evidence = [_ev_cash(self.ctx.cash_movements[-1])] if self.ctx.cash_movements else []
            return True, evidence
        return False, []

    def _op_transaction_status(self, statuses, after=None):
        statuses = _as_list(statuses)
        if self.ctx.status in statuses:
            return True, []
        return False, []

    def _op_host_state(self, states, after=None):
        states = _as_list(states)
        if self.ctx.host_state() in states:
            return True, []
        return False, []

    def _op_error_code_prefix(self, prefix, after=None):
        hits = [
            e
            for e in self.ctx.events
            if _error_code_of(e) and str(_error_code_of(e)).startswith(str(prefix))
        ]
        return (True, [_ev_event(e) for e in hits[:8]]) if hits else (False, [])

    def _op_error_code_any(self, codes, after=None):
        codes = {str(c) for c in _as_list(codes)}
        hits = [e for e in self.ctx.events if _error_code_of(e) in codes]
        return (True, [_ev_event(e) for e in hits[:8]]) if hits else (False, [])

    def _op_reconciliation(self, names, after=None):
        names = _as_list(names)
        hits = [i for i in self.ctx.reconciliation if i.name in names]
        if not hits:
            return False, []
        evidence = []
        for issue in hits:
            evidence.append(
                {
                    "kind": "reconciliation",
                    "issue": issue.name,
                    "detail": issue.detail,
                }
            )
            evidence += issue.evidence
        return True, evidence


def _error_code_of(e) -> str | None:
    detail = getattr(e, "detail", None)
    if isinstance(detail, dict):
        return detail.get("error_code")
    return None


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def engine_for(model_code: str | None) -> DiagnosticEngine:
    """Build the engine from universal rules + the model's overlay."""
    return DiagnosticEngine(DiagnosticConfig.load(model_code))
