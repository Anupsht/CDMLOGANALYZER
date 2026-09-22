"""Phase 4: cash lifecycle, hardware correlation & jam classification.

This module is the *universal* hardware analysis engine. It consumes the
normalized events of ONE transaction plus the model's ``hardware.yaml``
configuration (patterns, timeouts, windows — all data) and produces:

* cash lifecycle movements  (UNKNOWN → … → STORED / RETURNED / JAMMED …)
* structured sensor / motor / gate / shutter / transport records
* an evidence-based fault assessment with one of the classifications
  CONFIRMED_JAM | PROBABLE_JAM | POSSIBLE_JAM | NO_EVIDENCE_OF_JAM |
  INSUFFICIENT_DATA

Non-negotiable rules:
* **No model code in the engine.** Everything model-specific (line
  patterns, motor names, timeouts, temporal windows, jam indications)
  comes from ``hardware.yaml``.
* **Never invent values.** Missing note fields stay ``UNKNOWN``, a
  position never observed stays ``None``, a stage without evidence is
  reported as such.
* **A single error code is never a confirmed jam.** Classification
  requires the evidence combinations implemented in :class:`JamClassifier`.
* **No unsupported conclusions.** Statements report observed facts and
  hedged hypotheses ("consistent with a transport obstruction…"), never
  component-level root causes ("motor is damaged").
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.analysis import events as E

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Universal cash lifecycle states
# ---------------------------------------------------------------------------

LS_UNKNOWN = "UNKNOWN"
LS_INSERTED = "INSERTED"
LS_ACCEPTED = "ACCEPTED"
LS_VALIDATED = "VALIDATED"
LS_COUNTED = "COUNTED"
LS_ESCROW = "ESCROW"
LS_CONFIRMED = "CONFIRMED"
LS_TRANSPORTING = "TRANSPORTING"
LS_STORED = "STORED"
LS_REJECTED = "REJECTED"
LS_RETURNED = "RETURNED"
LS_JAMMED = "JAMMED"
LS_UNKNOWN_LOCATION = "UNKNOWN_LOCATION"

CASH_LIFECYCLE_STATES: tuple[str, ...] = (
    LS_UNKNOWN,
    LS_INSERTED,
    LS_ACCEPTED,
    LS_VALIDATED,
    LS_COUNTED,
    LS_ESCROW,
    LS_CONFIRMED,
    LS_TRANSPORTING,
    LS_STORED,
    LS_REJECTED,
    LS_RETURNED,
    LS_JAMMED,
    LS_UNKNOWN_LOCATION,
)

# Universal event → lifecycle state. Models reach these universal codes via
# their own events.yaml mappings; the mapping may be extended per model
# through hardware.yaml ``cash.lifecycle_overrides``.
DEFAULT_EVENT_TO_STATE: dict[str, str] = {
    E.CASH_INSERTED: LS_INSERTED,
    E.CASH_ACCEPTED: LS_ACCEPTED,
    E.CASH_ESCROWED: LS_ESCROW,
    E.CASH_COUNTING_COMPLETED: LS_COUNTED,
    E.VALIDATION_PASSED: LS_VALIDATED,
    E.VALIDATION_FAILED: LS_REJECTED,  # failed validation → reject path
    E.HOST_RESPONSE: LS_CONFIRMED,
    E.CASH_STORED: LS_STORED,
    E.CASH_REJECTED: LS_REJECTED,
    E.CASH_RETURNED: LS_RETURNED,
    E.JAM_DETECTED: LS_JAMMED,
}

# States in which the cash is physically held before/while transport runs.
_PRE_TRANSPORT = frozenset(
    {LS_INSERTED, LS_ACCEPTED, LS_ESCROW, LS_COUNTED, LS_VALIDATED, LS_CONFIRMED}
)
_TERMINAL_STATES = frozenset({LS_STORED, LS_REJECTED, LS_RETURNED})

CONFIDENCE_DIRECT = 1.0  # a universal event directly implies the state
CONFIDENCE_INFERRED = 0.7  # TRANSPORTING inferred from transport-motor start

# ---------------------------------------------------------------------------
# Fault classifications
# ---------------------------------------------------------------------------

CONFIRMED_JAM = "CONFIRMED_JAM"
PROBABLE_JAM = "PROBABLE_JAM"
POSSIBLE_JAM = "POSSIBLE_JAM"
NO_EVIDENCE_OF_JAM = "NO_EVIDENCE_OF_JAM"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

JAM_CLASSIFICATIONS: tuple[str, ...] = (
    CONFIRMED_JAM,
    PROBABLE_JAM,
    POSSIBLE_JAM,
    NO_EVIDENCE_OF_JAM,
    INSUFFICIENT_DATA,
)

_TRANSPORT_OUTCOMES: tuple[str, ...] = (
    "COMPLETED",
    "TIMEOUT",
    "MISSING_SENSOR_TRANSITION",
    "REPEATED_MOVEMENT",
    "UNEXPECTED_STATE",
    "UNKNOWN",
)


# ---------------------------------------------------------------------------
# Configuration (from hardware.yaml — all data, no model branching)
# ---------------------------------------------------------------------------


@dataclass
class MotorCfg:
    name: str = "motor"
    start_re: "re.Pattern[str] | None" = None
    stop_re: "re.Pattern[str] | None" = None
    timeout_ms: int = 8000


@dataclass
class ActuatorCfg:  # gates & shutters
    command_re: "re.Pattern[str] | None" = None
    position_re: "re.Pattern[str] | None" = None
    transition_timeout_ms: int = 5000
    expected_state_map: dict[str, str] = field(default_factory=dict)  # command → expected position


@dataclass
class TransportSensorCfg:
    sensor: str
    expected: str  # expected state while transport is active
    blocked: tuple[str, ...] = ()  # states that indicate an unexpected condition


@dataclass
class TransportCfg:
    motor_names: tuple[str, ...] = ()
    timeout_ms: int = 10000
    sensors: tuple[TransportSensorCfg, ...] = ()


@dataclass
class TemporalCfg:
    before_seconds: int = 30
    after_seconds: int = 60
    per_device: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class HardwareConfig:
    """Compiled hardware.yaml. ``absent`` = model ships no hardware config."""

    absent: bool = True
    sensors: tuple["re.Pattern[str]", ...] = ()
    motors: tuple[MotorCfg, ...] = ()
    gates: ActuatorCfg | None = None
    shutters: ActuatorCfg | None = None
    transport: TransportCfg = field(default_factory=TransportCfg)
    temporal: TemporalCfg = field(default_factory=TemporalCfg)
    jam_patterns: tuple["re.Pattern[str]", ...] = ()
    jam_events: tuple[str, ...] = (E.JAM_DETECTED,)
    note_extract: tuple[tuple[str, "re.Pattern[str]", str], ...] = ()  # (key, regex, type)
    lifecycle_overrides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, cfg: dict[str, Any] | None) -> "HardwareConfig":
        if not cfg:
            return cls(absent=True)
        compiled = cls(absent=False)

        compiled.sensors = tuple(
            re.compile(rule["pattern"], re.IGNORECASE)
            for rule in cfg.get("sensors", [])
            if isinstance(rule, dict) and rule.get("pattern")
        )
        motors = []
        for rule in cfg.get("motors", []):
            if not isinstance(rule, dict):
                continue
            motors.append(
                MotorCfg(
                    name=str(rule.get("name", "motor")),
                    start_re=re.compile(rule["start_pattern"], re.IGNORECASE) if rule.get("start_pattern") else None,
                    stop_re=re.compile(rule["stop_pattern"], re.IGNORECASE) if rule.get("stop_pattern") else None,
                    timeout_ms=int(rule.get("timeout_ms", 8000)),
                )
            )
        compiled.motors = tuple(motors)

        def _actuator(key: str) -> ActuatorCfg | None:
            rule = cfg.get(key)
            if not isinstance(rule, dict):
                return None
            return ActuatorCfg(
                command_re=re.compile(rule["command_pattern"], re.IGNORECASE) if rule.get("command_pattern") else None,
                position_re=re.compile(rule["position_pattern"], re.IGNORECASE) if rule.get("position_pattern") else None,
                transition_timeout_ms=int(rule.get("transition_timeout_ms", 5000)),
                expected_state_map={k: str(v) for k, v in (rule.get("expected_state_map") or {}).items()},
            )

        compiled.gates = _actuator("gates")
        compiled.shutters = _actuator("shutters")

        tr = cfg.get("transport") or {}
        sensors = tuple(
            TransportSensorCfg(
                sensor=str(s["sensor"]),
                expected=str(s.get("expected", "OPEN")),
                blocked=tuple(str(b) for b in s.get("blocked", [])),
            )
            for s in tr.get("sensors", [])
            if isinstance(s, dict) and s.get("sensor")
        )
        compiled.transport = TransportCfg(
            motor_names=tuple(str(m).upper() for m in tr.get("motor_names", [])),
            timeout_ms=int(tr.get("timeout_ms", 10000)),
            sensors=sensors,
        )

        tmp = cfg.get("temporal_analysis") or {}
        compiled.temporal = TemporalCfg(
            before_seconds=int(tmp.get("before_seconds", 30)),
            after_seconds=int(tmp.get("after_seconds", 60)),
            per_device={k: dict(v) for k, v in (tmp.get("per_device") or {}).items()},
        )

        jam = cfg.get("jam_indications") or {}
        compiled.jam_patterns = tuple(re.compile(p, re.IGNORECASE) for p in (jam.get("patterns") or []))
        compiled.jam_events = tuple(jam.get("events") or (E.JAM_DETECTED,))

        compiled.note_extract = tuple(
            (
                str(rule["key"]),
                re.compile(rule["pattern"], re.IGNORECASE),
                str(rule.get("type", "str")),
            )
            for rule in ((cfg.get("cash") or {}).get("notes") or [])
            if isinstance(rule, dict) and rule.get("pattern") and rule.get("key")
        )
        compiled.lifecycle_overrides = {
            str(k): str(v)
            for k, v in ((cfg.get("cash") or {}).get("lifecycle_overrides") or {}).items()
        }
        return compiled


# ---------------------------------------------------------------------------
# Records (pre-persistence)
# ---------------------------------------------------------------------------


@dataclass
class Movement:
    from_state: str
    to_state: str
    timestamp: datetime | None
    device: str | None
    evidence_event: str
    confidence: float
    note_id: str | None = None
    note_info: dict | None = None
    log_file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None


@dataclass
class SensorRecord:
    sensor: str
    previous_state: str | None
    new_state: str | None
    timestamp: datetime | None
    expected_state: str | None = None
    actual_state: str | None = None
    abnormal_duration_ms: int | None = None
    device: str | None = None
    log_file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None
    detail: dict | None = None


@dataclass
class MotorRecord:
    motor: str
    started_at: datetime | None
    stopped_at: datetime | None
    duration_ms: int | None
    timeout_ms: int
    timed_out: bool
    transport_name: str | None
    sensor_transitions: list[str] = field(default_factory=list)
    device: str | None = None
    log_file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None
    stop_line_number: int | None = None
    stop_raw_text: str | None = None


@dataclass
class GateRecord:  # gates and shutters
    kind: str  # gate | shutter
    name: str
    command: str | None
    expected_state: str | None
    actual_state: str | None  # None = position never observed
    transition_ms: int | None
    timeout_ms: int
    timed_out: bool
    state_mismatch: bool
    device: str | None = None
    log_file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None
    position_evidence: dict | None = None


@dataclass
class TransportRecord:
    name: str
    started_at: datetime | None
    ended_at: datetime | None
    outcome: str  # one of _TRANSPORT_OUTCOMES
    timeout_ms: int
    detail: dict = field(default_factory=dict)
    device: str | None = None
    log_file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None


@dataclass
class Fault:
    subject_kind: str
    subject_name: str | None
    classification: str
    statement: str
    evidence: list[dict] = field(default_factory=list)
    analysis_window: dict = field(default_factory=dict)


@dataclass
class HardwareReport:
    final_cash_state: str
    movements: list[Movement] = field(default_factory=list)
    sensors: list[SensorRecord] = field(default_factory=list)
    motors: list[MotorRecord] = field(default_factory=list)
    gates: list[GateRecord] = field(default_factory=list)
    shutters: list[GateRecord] = field(default_factory=list)
    transports: list[TransportRecord] = field(default_factory=list)
    faults: list[Fault] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal primitives
# ---------------------------------------------------------------------------


@dataclass
class _Primitive:
    """A hardware primitive extracted from one normalized event's raw text."""

    kind: str  # sensor | motor_start | motor_stop | gate_cmd | gate_pos | shtr_cmd | shtr_pos | jam
    name: str
    value: dict[str, Any]
    event_code: str
    timestamp: datetime | None
    device: str | None
    log_file_id: str | None
    line_number: int | None
    raw_text: str


def _ms(delta_seconds: float) -> int:
    return int(round(delta_seconds * 1000))


def _code(ev) -> str:
    return getattr(ev, "event_code", getattr(ev, "event", ""))


class HardwareAnalyzer:
    """Config-driven analyzer bound to one model's hardware.yaml."""

    def __init__(self, config: HardwareConfig) -> None:
        self.cfg = config

    # -- public entry point ---------------------------------------------------

    def analyze(self, events: list) -> HardwareReport:
        ordered = self._sort_events(events)
        primitives = self._extract_primitives(ordered)
        sensors = self._sensor_records(ordered)
        motors, repeats = self._pair_motors(primitives, sensors)
        gates = self._pair_actuators("gate", primitives)
        shutters = self._pair_actuators("shutter", primitives)
        transports = self._pair_transports(motors, sensors)
        movements = self._cash_movements(ordered, primitives)
        faults = JamClassifier(self.cfg).assess(
            ordered=ordered,
            primitives=primitives,
            motors=motors,
            gates=gates,
            shutters=shutters,
            transports=transports,
            movements=movements,
            repeats=repeats,
        )
        return HardwareReport(
            final_cash_state=self.final_cash_state(movements),
            movements=movements,
            sensors=sensors,
            motors=motors,
            gates=gates,
            shutters=shutters,
            transports=transports,
            faults=faults,
        )

    def final_cash_state(self, movements: list[Movement]) -> str:
        if not movements:
            return LS_UNKNOWN
        last = movements[-1].to_state
        if last in _TERMINAL_STATES or last == LS_JAMMED:
            return last
        # Cash entered the machine but its location was never resolved.
        return LS_UNKNOWN_LOCATION

    # -- extraction --------------------------------------------------------------

    def _sort_events(self, events: list) -> list:
        return sorted(events, key=lambda e: (e.timestamp or datetime.min, e.line_number or 0))

    def _prim(self, kind: str, name: str, value: dict, ev, groups: dict) -> _Primitive:
        return _Primitive(
            kind=kind,
            name=name,
            value=value,
            event_code=_code(ev),
            timestamp=ev.timestamp,
            device=ev.device,
            log_file_id=ev.log_file_id,
            line_number=ev.line_number,
            raw_text=(ev.raw_text or "")[:400],
        )

    def _extract_primitives(self, events: list) -> list[_Primitive]:
        out: list[_Primitive] = []
        for ev in events:
            raw = ev.raw_text or ""
            matched = False
            for pattern in self.cfg.sensors:
                m = pattern.search(raw)
                if m:
                    gd = m.groupdict()
                    out.append(
                        self._prim(
                            "sensor",
                            str(gd.get("name") or "sensor"),
                            {"previous": gd.get("previous"), "new": gd.get("new")},
                            ev,
                            gd,
                        )
                    )
                    matched = True
                    break
            if not matched:
                for mcfg in self.cfg.motors:
                    if mcfg.start_re:
                        m = mcfg.start_re.search(raw)
                        if m:
                            gd = m.groupdict()
                            out.append(
                                self._prim("motor_start", str(gd.get("name") or mcfg.name), {}, ev, gd)
                            )
                            matched = True
                            break
                    if mcfg.stop_re:
                        m = mcfg.stop_re.search(raw)
                        if m:
                            gd = m.groupdict()
                            out.append(
                                self._prim("motor_stop", str(gd.get("name") or mcfg.name), {}, ev, gd)
                            )
                            matched = True
                            break
            if not matched:
                for act_key, kind_prefix in (("gates", "gate"), ("shutters", "shtr")):
                    act = getattr(self.cfg, act_key)
                    if act is None:
                        continue
                    if act.command_re:
                        m = act.command_re.search(raw)
                        if m:
                            gd = m.groupdict()
                            out.append(
                                self._prim(
                                    f"{kind_prefix}_cmd",
                                    str(gd.get("name") or kind_prefix),
                                    {"command": str(gd.get("command") or "").upper()},
                                    ev,
                                    gd,
                                )
                            )
                            matched = True
                            break
                    if act.position_re:
                        m = act.position_re.search(raw)
                        if m:
                            gd = m.groupdict()
                            out.append(
                                self._prim(
                                    f"{kind_prefix}_pos",
                                    str(gd.get("name") or kind_prefix),
                                    {"state": str(gd.get("state") or "").upper()},
                                    ev,
                                    gd,
                                )
                            )
                            matched = True
                            break
        return out

    # -- sensors -----------------------------------------------------------------

    def _sensor_records(self, events: list) -> list[SensorRecord]:
        recs: list[SensorRecord] = []
        for ev in events:
            raw = ev.raw_text or ""
            for pattern in self.cfg.sensors:
                m = pattern.search(raw)
                if m:
                    gd = m.groupdict()
                    recs.append(
                        SensorRecord(
                            sensor=str(gd.get("name") or "sensor"),
                            previous_state=gd.get("previous"),
                            new_state=gd.get("new"),
                            timestamp=ev.timestamp,
                            actual_state=gd.get("new"),
                            device=ev.device,
                            log_file_id=ev.log_file_id,
                            line_number=ev.line_number,
                            raw_text=(raw or "")[:400],
                        )
                    )
                    break
        recs.sort(key=lambda r: (r.timestamp or datetime.min, r.line_number or 0))
        return recs

    # -- motors --------------------------------------------------------------------

    def _motor_timeout_ms(self, name: str) -> int:
        upper = name.upper()
        for mcfg in self.cfg.motors:
            if mcfg.name.upper() == upper:
                return mcfg.timeout_ms
        return self.cfg.motors[0].timeout_ms if self.cfg.motors else 8000

    def _pair_motors(self, primitives, sensors) -> tuple[list[MotorRecord], int]:
        """Pair start/stop per motor. Returns (records, repeated_movements)."""
        starts = [p for p in primitives if p.kind == "motor_start"]
        stops = [p for p in primitives if p.kind == "motor_stop"]
        records: list[MotorRecord] = []
        repeated = 0
        open_runs: dict[str, _Primitive] = {}
        ordered = sorted(starts + stops, key=lambda p: (p.timestamp or datetime.min, p.line_number or 0))
        for prim in ordered:
            if prim.kind == "motor_start":
                if prim.name in open_runs:
                    # New start before the previous run stopped: the previous
                    # stop is missing (never invent one).
                    repeated += 1
                    prev = open_runs.pop(prim.name)
                    records.append(
                        self._motor_record(prev, None, self._motor_timeout_ms(prim.name), primitives, sensors)
                    )
                open_runs[prim.name] = prim
            else:
                start = open_runs.pop(prim.name, None)
                if start is None:
                    continue  # stop without start: kept as raw evidence only
                records.append(
                    self._motor_record(start, prim, self._motor_timeout_ms(prim.name), primitives, sensors)
                )
        for name, start in open_runs.items():
            records.append(
                self._motor_record(start, None, self._motor_timeout_ms(name), primitives, sensors)
            )
        records.sort(key=lambda r: (r.started_at or datetime.min, r.line_number or 0))
        return records, repeated

    def _motor_record(
        self, start: _Primitive, stop: _Primitive | None, timeout_ms: int, primitives, sensors
    ) -> MotorRecord:
        duration_ms: int | None = None
        timed_out = False
        if stop is not None and start.timestamp is not None and stop.timestamp is not None:
            duration_ms = _ms((stop.timestamp - start.timestamp).total_seconds())
            timed_out = duration_ms > timeout_ms
        else:
            # No stop observed within the analyzed events → stop missing.
            timed_out = True
        is_transport = start.name.upper() in self.cfg.transport.motor_names
        window_start = start.timestamp
        window_end = stop.timestamp if stop else None
        transitions = [
            f"{s.sensor}:{s.previous_state}->{s.new_state}"
            for s in sensors
            if window_start is not None
            and s.timestamp is not None
            and s.timestamp >= window_start
            and (window_end is None or s.timestamp <= window_end)
        ]
        return MotorRecord(
            motor=start.name,
            started_at=start.timestamp,
            stopped_at=stop.timestamp if stop else None,
            duration_ms=duration_ms,
            timeout_ms=timeout_ms,
            timed_out=timed_out,
            transport_name=start.name if is_transport else None,
            sensor_transitions=transitions,
            device=start.device,
            log_file_id=start.log_file_id,
            line_number=start.line_number,
            raw_text=start.raw_text,
            stop_line_number=stop.line_number if stop else None,
            stop_raw_text=stop.raw_text if stop else None,
        )

    # -- gates / shutters --------------------------------------------------------------

    def _pair_actuators(self, kind: str, primitives) -> list[GateRecord]:
        act = self.cfg.gates if kind == "gate" else self.cfg.shutters
        if act is None:
            return []
        prefix = "shtr" if kind == "shutter" else kind
        cmds = [p for p in primitives if p.kind == f"{prefix}_cmd"]
        poss = [p for p in primitives if p.kind == f"{prefix}_pos"]
        poss.sort(key=lambda p: (p.timestamp or datetime.min, p.line_number or 0))
        records: list[GateRecord] = []
        for cmd in cmds:
            command = cmd.value.get("command")
            expected = act.expected_state_map.get(command or "", command)
            match: _Primitive | None = None
            if cmd.timestamp is not None:
                for pos in poss:
                    if pos.name != cmd.name or pos.timestamp is None or pos.timestamp < cmd.timestamp:
                        continue
                    match = pos
                    break
            else:
                match = next((p for p in poss if p.name == cmd.name), None)
            if match is None:
                records.append(
                    GateRecord(
                        kind=kind,
                        name=cmd.name,
                        command=command,
                        expected_state=expected,
                        actual_state=None,
                        transition_ms=None,
                        timeout_ms=act.transition_timeout_ms,
                        timed_out=True,
                        state_mismatch=False,
                        device=cmd.device,
                        log_file_id=cmd.log_file_id,
                        line_number=cmd.line_number,
                        raw_text=cmd.raw_text,
                    )
                )
                continue
            actual = match.value.get("state")
            transition_ms = (
                _ms((match.timestamp - cmd.timestamp).total_seconds())
                if cmd.timestamp is not None and match.timestamp is not None
                else None
            )
            records.append(
                GateRecord(
                    kind=kind,
                    name=cmd.name,
                    command=command,
                    expected_state=expected,
                    actual_state=actual,
                    transition_ms=transition_ms,
                    timeout_ms=act.transition_timeout_ms,
                    timed_out=(transition_ms is not None and transition_ms > act.transition_timeout_ms),
                    state_mismatch=(actual is not None and expected is not None and actual != expected),
                    device=cmd.device,
                    log_file_id=cmd.log_file_id,
                    line_number=cmd.line_number,
                    raw_text=cmd.raw_text,
                    position_evidence={
                        "file_id": match.log_file_id,
                        "line_number": match.line_number,
                        "raw_text": match.raw_text,
                        "timestamp": match.timestamp.isoformat() if match.timestamp else None,
                    },
                )
            )
        return records

    # -- transport ------------------------------------------------------------------------

    def _pair_transports(self, motors: list[MotorRecord], sensors: list[SensorRecord]) -> list[TransportRecord]:
        tcfg = self.cfg.transport
        if not tcfg.motor_names:
            return []
        records: list[TransportRecord] = []
        for run in [m for m in motors if m.transport_name]:
            detail: dict[str, Any] = {"expected_sensors": [s.sensor for s in tcfg.sensors]}
            observed: list[str] = []
            unexpected: list[str] = []
            missing: list[str] = []
            if run.started_at is not None:
                window_end = run.stopped_at
                for scfg in tcfg.sensors:
                    hits = [
                        s
                        for s in sensors
                        if s.sensor == scfg.sensor
                        and s.timestamp is not None
                        and s.timestamp >= run.started_at
                        and (window_end is None or s.timestamp <= window_end)
                    ]
                    if hits:
                        observed.append(scfg.sensor)
                        last = hits[-1]
                        if scfg.expected and last.new_state != scfg.expected and last.new_state in (scfg.blocked or ()):
                            unexpected.append(scfg.sensor)
                            last.expected_state = scfg.expected
                    else:
                        missing.append(scfg.sensor)
                # Late sensor arrivals: only for expectations that were
                # MISSING during the run (a late fulfillment is abnormal;
                # a second, expected transition after the run is not).
                for scfg in tcfg.sensors:
                    if scfg.sensor not in missing:
                        continue
                    for s in sensors:
                        if (
                            s.sensor == scfg.sensor
                            and s.timestamp is not None
                            and window_end is not None
                            and s.timestamp > window_end
                            and s.abnormal_duration_ms is None
                        ):
                            s.abnormal_duration_ms = _ms((s.timestamp - window_end).total_seconds())
                            s.expected_state = s.expected_state or scfg.expected
            detail.update({"observed": observed, "missing": missing, "unexpected": unexpected})

            if run.stopped_at is not None and not run.timed_out:
                if unexpected:
                    outcome = "UNEXPECTED_STATE"
                elif missing:
                    outcome = "MISSING_SENSOR_TRANSITION"
                else:
                    outcome = "COMPLETED"
            else:
                # No stop observed, or run exceeded the configured timeout.
                outcome = "TIMEOUT"
            records.append(
                TransportRecord(
                    name=run.motor,
                    started_at=run.started_at,
                    ended_at=run.stopped_at,
                    outcome=outcome,
                    timeout_ms=tcfg.timeout_ms,
                    detail=detail,
                    device=run.device,
                    log_file_id=run.log_file_id,
                    line_number=run.line_number,
                    raw_text=run.raw_text,
                )
            )
        records.sort(key=lambda r: (r.started_at or datetime.min, r.line_number or 0))
        return records

    # -- cash lifecycle ---------------------------------------------------------------------

    def _event_state(self, code: str) -> str | None:
        return self.cfg.lifecycle_overrides.get(code) or DEFAULT_EVENT_TO_STATE.get(code)

    def _cash_movements(self, events, primitives) -> list[Movement]:
        transport_motors = set(self.cfg.transport.motor_names)
        current = LS_UNKNOWN
        movements: list[Movement] = []
        prim_by_line = {
            (p.event_code, p.line_number): p for p in primitives if p.kind == "motor_start"
        }
        for ev in events:
            code = _code(ev)
            ts = ev.timestamp
            device = ev.device

            # Inferred TRANSPORTING transition on transport-motor start.
            motor_started: str | None = None
            if code in (E.MOTOR_STARTED, E.TRANSPORT_STARTED):
                prim = prim_by_line.get((code, ev.line_number))
                if prim is not None:
                    motor_started = prim.name
                elif code == E.TRANSPORT_STARTED:
                    motor_started = "transport"
            if (
                motor_started is not None
                and motor_started.upper() in transport_motors
                and current in _PRE_TRANSPORT
            ):
                movements.append(self._movement(current, LS_TRANSPORTING, ev, CONFIDENCE_INFERRED))
                current = LS_TRANSPORTING

            state = self._event_state(code)
            if state is not None and state != current:
                movement = self._movement(current, state, ev, CONFIDENCE_DIRECT)
                movement.note_info = self._note_info(ev)
                movements.append(movement)
                current = state
        return movements

    @staticmethod
    def _movement(from_state: str, to_state: str, ev, confidence: float) -> Movement:
        return Movement(
            from_state=from_state,
            to_state=to_state,
            timestamp=ev.timestamp,
            device=ev.device,
            evidence_event=_code(ev),
            confidence=confidence,
            log_file_id=ev.log_file_id,
            line_number=ev.line_number,
            raw_text=(ev.raw_text or "")[:400],
        )

    def _note_info(self, ev) -> dict | None:
        if not self.cfg.note_extract:
            return None
        raw = ev.raw_text or ""
        info: dict[str, Any] = {}
        for key, pattern, value_type in self.cfg.note_extract:
            value: Any = "UNKNOWN"  # missing values are never invented
            m = pattern.search(raw)
            if m:
                raw_value = m.group(1) if m.groups() else m.group(0)
                try:
                    value = (
                        float(raw_value)
                        if value_type == "float"
                        else int(raw_value) if value_type == "int" else str(raw_value)
                    )
                except (TypeError, ValueError):
                    value = str(raw_value)
            info[key] = value
        return info or None


# ---------------------------------------------------------------------------
# Jam classification (evidence combinations — never a single error code)
# ---------------------------------------------------------------------------


class JamClassifier:
    def __init__(self, config: HardwareConfig) -> None:
        self.cfg = config

    def assess(
        self,
        *,
        ordered: list,
        primitives: list[_Primitive],
        motors: list[MotorRecord],
        gates: list[GateRecord],
        shutters: list[GateRecord],
        transports: list[TransportRecord],
        movements: list[Movement],
        repeats: int,
    ) -> list[Fault]:
        facts: list[str] = []
        evidence: list[dict] = []
        primary: _Primitive | None = None
        subject_kind, subject_name = "transaction", None

        jam_prims = self._jam_events(ordered)
        transport_timeout_events = [ev for ev in ordered if _code(ev) == E.TRANSPORT_TIMEOUT]
        transport_timeouts = [t for t in transports if t.outcome == "TIMEOUT"]
        missing = [t for t in transports if t.outcome == "MISSING_SENSOR_TRANSITION"]
        unexpected = [t for t in transports if t.outcome == "UNEXPECTED_STATE"]
        motor_timeouts = [m for m in motors if m.timed_out and not m.transport_name]

        def _take_prim(cand: _Primitive | None, kind: str, name: str | None) -> None:
            nonlocal primary, subject_kind, subject_name
            if primary is None and cand is not None:
                primary = cand
                subject_kind, subject_name = kind, name

        for prim in jam_prims:
            facts.append(
                f"explicit jam indication in the logs at {prim.timestamp} "
                f"(line {prim.line_number}: {prim.raw_text[:80]})"
            )
            evidence.append(self._ev("jam_indication", prim))
            _take_prim(prim, "transport", prim.name or None)
        for t in transport_timeouts:
            facts.append(
                f"transport {t.name} did not complete within the configured {t.timeout_ms} ms window"
                + ("" if t.ended_at else " and no stop event was observed")
            )
            evidence.append(self._ev("transport_timeout", _prim_of(t)))
            _take_prim(_prim_of(t), "transport", t.name)
            if t.detail.get("missing"):
                facts.append(
                    f"expected sensor transition(s) not observed during transport {t.name}: "
                    f"{', '.join(t.detail['missing'])}"
                )
                evidence.append(self._ev("missing_sensor_transition", _prim_of(t)))
        for ev in transport_timeout_events:
            facts.append(f"transport timeout reported by the logs at {ev.timestamp} (line {ev.line_number})")
            p = _prim_of_event(ev)
            evidence.append(self._ev("transport_timeout", p))
            _take_prim(p, "transport", None)
        for t in missing:
            names = ", ".join(t.detail.get("missing", [])) or "unknown"
            facts.append(f"expected sensor transition(s) not observed during transport {t.name}: {names}")
            evidence.append(self._ev("missing_sensor_transition", _prim_of(t)))
        for t in unexpected:
            facts.append(
                f"unexpected sensor state during transport {t.name}: {', '.join(t.detail.get('unexpected', []))}"
            )
            evidence.append(self._ev("unexpected_state", _prim_of(t)))
        for m in motor_timeouts:
            facts.append(
                f"motor {m.motor} exceeded its {m.timeout_ms} ms timeout"
                + (f" (ran {m.duration_ms} ms)" if m.duration_ms is not None else " (no stop event observed)")
            )
            evidence.append(self._ev("motor_timeout", _prim_of(m)))
            _take_prim(_prim_of(m), "motor", m.motor)
        for g in gates:
            if g.state_mismatch:
                facts.append(f"gate {g.name} position {g.actual_state} did not match commanded {g.expected_state}")
                evidence.append(self._ev("gate_mismatch", _prim_of(g)))
                _take_prim(_prim_of(g), "gate", g.name)
            elif g.timed_out:
                facts.append(f"gate {g.name} position not observed within {g.timeout_ms} ms")
                evidence.append(self._ev("gate_timeout", _prim_of(g)))
                _take_prim(_prim_of(g), "gate", g.name)
        for g in shutters:
            if g.state_mismatch:
                facts.append(f"shutter {g.name} position {g.actual_state} did not match commanded {g.expected_state}")
                evidence.append(self._ev("shutter_mismatch", _prim_of(g)))
                _take_prim(_prim_of(g), "shutter", g.name)
            elif g.timed_out:
                facts.append(f"shutter {g.name} position not observed within {g.timeout_ms} ms")
                evidence.append(self._ev("shutter_timeout", _prim_of(g)))
                _take_prim(_prim_of(g), "shutter", g.name)
        if repeats:
            facts.append(f"repeated transport start without an intervening stop ({repeats}x)")
            if transports:
                _take_prim(_prim_of(transports[0]), "transport", transports[0].name)

        # --- classification (evidence combinations) ---------------------------
        transport_flag = bool(transport_timeouts or transport_timeout_events)
        missing_flag = bool(missing) or any(t.detail.get("missing") for t in transport_timeouts)
        unexpected_flag = bool(unexpected)
        motor_flag = bool(motor_timeouts)
        repeat_flag = bool(repeats)
        gate_flag = any(g.state_mismatch or g.timed_out for g in gates)
        shutter_flag = any(s.state_mismatch or s.timed_out for s in shutters)
        jam_flag = bool(jam_prims)
        anomaly = transport_flag or missing_flag or motor_flag or unexpected_flag or repeat_flag or gate_flag or shutter_flag
        has_hardware_evidence = bool(transports or motors or movements)

        if jam_flag and (transport_flag or missing_flag or motor_flag or unexpected_flag or gate_flag or shutter_flag):
            classification = CONFIRMED_JAM
        elif jam_flag:
            classification = PROBABLE_JAM
        elif transport_flag and (missing_flag or unexpected_flag):
            classification = PROBABLE_JAM
        elif anomaly:
            classification = POSSIBLE_JAM
        elif movements and movements[-1].to_state in _TERMINAL_STATES:
            classification = NO_EVIDENCE_OF_JAM
        elif has_hardware_evidence:
            # Cash present but neither terminal nor anomalous: not enough
            # information to either confirm or exclude a jam.
            classification = INSUFFICIENT_DATA
        else:
            classification = INSUFFICIENT_DATA

        if classification == NO_EVIDENCE_OF_JAM:
            facts = ["cash reached a terminal state: " + movements[-1].to_state]
            facts += [
                f"transport {t.name} completed within the configured window"
                for t in transports
                if t.outcome == "COMPLETED"
            ]
            evidence = [_ev_static("terminal_state", _prim_of_movement(movements[-1]))]
            subject_kind, subject_name = "transaction", None
        elif classification == INSUFFICIENT_DATA and not facts:
            facts = ["no cash-transport, sensor or motor evidence in the analyzed events"]
            subject_kind = "transaction"

        # When a jam indication is corroborated by transport evidence, the
        # assessment subject is the transport (its name drives per-device
        # window overrides); the window anchor stays on the first anomaly.
        if classification in (CONFIRMED_JAM, PROBABLE_JAM):
            if transport_timeouts:
                subject_kind, subject_name = "transport", transport_timeouts[0].name
            elif missing or unexpected:
                first = (missing or unexpected)[0]
                subject_kind, subject_name = "transport", first.name

        # --- temporal correlation window ----------------------------------------
        window: dict[str, Any] = {
            "before_seconds": self.cfg.temporal.before_seconds,
            "after_seconds": self.cfg.temporal.after_seconds,
        }
        t0 = primary.timestamp if primary else None
        if t0 is not None:
            override = self.cfg.temporal.per_device.get(subject_name or "", {})
            before = int(override.get("before_seconds", self.cfg.temporal.before_seconds))
            after = int(override.get("after_seconds", self.cfg.temporal.after_seconds))
            window.update(
                {
                    "before_seconds": before,
                    "after_seconds": after,
                    "from": (t0 - timedelta(seconds=before)).isoformat(),
                    "to": (t0 + timedelta(seconds=after)).isoformat(),
                }
            )
            lo, hi = t0 - timedelta(seconds=before), t0 + timedelta(seconds=after)
            for ev in ordered:
                if ev.timestamp is not None and lo <= ev.timestamp <= hi:
                    item = _ev_static(_code(ev), _prim_of_event(ev))
                    if item not in evidence:
                        evidence.append(item)

        return [
            Fault(
                subject_kind=subject_kind,
                subject_name=subject_name,
                classification=classification,
                statement=self._statement(classification, facts),
                evidence=evidence,
                analysis_window=window,
            )
        ]

    # -- helpers ----------------------------------------------------------------

    def _jam_events(self, ordered: list) -> list[_Primitive]:
        out = []
        for ev in ordered:
            raw = ev.raw_text or ""
            code = _code(ev)
            if any(p.search(raw) for p in self.cfg.jam_patterns) or code in self.cfg.jam_events:
                out.append(
                    _Primitive(
                        kind="jam",
                        name=self._device_of(ev) or "",
                        value={},
                        event_code=code,
                        timestamp=ev.timestamp,
                        device=ev.device,
                        log_file_id=ev.log_file_id,
                        line_number=ev.line_number,
                        raw_text=(raw or "")[:400],
                    )
                )
        return out

    @staticmethod
    def _device_of(ev) -> str | None:
        return getattr(ev, "device", None)

    @staticmethod
    def _ev(kind: str, prim: _Primitive | None) -> dict:
        if prim is None:
            return {"kind": kind, "timestamp": None}
        return {
            "kind": kind,
            "timestamp": prim.timestamp.isoformat() if prim.timestamp else None,
            "file_id": prim.log_file_id,
            "line_number": prim.line_number,
            "raw_text": prim.raw_text,
        }

    @staticmethod
    def _statement(classification: str, facts: list[str]) -> str:
        fact_list = "; ".join(facts)
        if classification == CONFIRMED_JAM:
            return (
                f"Jam confirmed by multiple independent log evidence: {fact_list}. "
                "The cash transport stopped under the conditions described above; the available "
                "logs do not identify a component-level root cause."
            )
        if classification == PROBABLE_JAM:
            return (
                f"A jam is probable: {fact_list}. "
                "The evidence is consistent with a transport obstruction; a motor-related or "
                "sensor-related problem is also possible. Component-level cause cannot be "
                "established from these logs alone."
            )
        if classification == POSSIBLE_JAM:
            return (
                f"A hardware anomaly was observed: {fact_list}. "
                "This is consistent with a possible transport obstruction or another "
                "transport-related problem, but it is not sufficient to confirm a jam."
            )
        if classification == NO_EVIDENCE_OF_JAM:
            return f"No evidence of a jam was found: {fact_list}."
        return (
            f"Insufficient data to assess a jam: {fact_list}. "
            "The available logs neither confirm nor exclude a jam."
        )


# ---------------------------------------------------------------------------
# adaptation helpers
# ---------------------------------------------------------------------------


def _prim_of(rec) -> _Primitive:
    return _Primitive(
        kind="record",
        name=str(getattr(rec, "motor", getattr(rec, "name", "")) or ""),
        value={},
        event_code="",
        timestamp=getattr(rec, "started_at", None),
        device=getattr(rec, "device", None),
        log_file_id=getattr(rec, "log_file_id", None),
        line_number=getattr(rec, "line_number", None),
        raw_text=(getattr(rec, "raw_text", "") or "")[:400],
    )


def _prim_of_event(ev) -> _Primitive:
    return _Primitive(
        kind="event",
        name="",
        value={},
        event_code=_code(ev),
        timestamp=ev.timestamp,
        device=ev.device,
        log_file_id=ev.log_file_id,
        line_number=ev.line_number,
        raw_text=(ev.raw_text or "")[:400],
    )


def _prim_of_movement(m: Movement) -> _Primitive:
    return _Primitive(
        kind="movement",
        name=m.to_state,
        value={},
        event_code=m.evidence_event,
        timestamp=m.timestamp,
        device=m.device,
        log_file_id=m.log_file_id,
        line_number=m.line_number,
        raw_text=(m.raw_text or "")[:400],
    )


def _ev_static(kind: str, prim: _Primitive | None) -> dict:
    return JamClassifier._ev(kind, prim)


def analyzer_for(model_code: str) -> HardwareAnalyzer | None:
    """Build the analyzer from a model's hardware.yaml (None if absent)."""
    from app.core.model_config import load_model_config

    cfg = (load_model_config(model_code) or {}).get("hardware")
    hw = HardwareConfig.from_yaml(cfg)
    if hw.absent:
        return None
    return HardwareAnalyzer(hw)
