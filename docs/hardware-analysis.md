# Hardware & cash-flow analysis (Phase 4)

How the system reconstructs **Transaction → Cash → Device →
Sensor/Motor/Gate → Fault → Final Cash State** — entirely from log
evidence, with raw file/line/text pointers on every derived record.

## 1. Where it runs

After transaction correlation, for every transaction whose model ships a
`hardware.yaml` package, the universal analyzer
(`backend/app/analysis/hardware.py`) runs over the stored normalized
events and persists:

| table | contents |
|---|---|
| `cash_movements` | lifecycle transitions (from_state → to_state, timestamp, device, evidence event, confidence, per-note metadata) |
| `sensor_events` | sensor transitions with expected/actual state and abnormal duration |
| `motor_events` | motor runs: start/stop, duration, timeout, transport association, sensor transitions observed during the run |
| `gate_events` | gate & shutter commands vs. observed positions (mismatch, transition time, timeout) |
| `transport_events` | transport runs and their outcome classification |
| `fault_assessments` | the jam classification + statement + evidence + analysis window |

The engine contains **no model-specific logic** — patterns, motor names,
timeouts, expected sensors, jam indications and temporal windows are all
data in `config/models/<code>/hardware.yaml` (currently SYNTHETIC — see
[model-integrations.md](model-integrations.md)).

Analysis runs at correlation time; transactions stored before a model
gained its `hardware.yaml` are analyzed lazily on first read of the
hardware endpoint, so the reconstruction chain is available for every
transaction of a hardware-capable model.

## 2. Cash lifecycle

Universal states:

```
UNKNOWN → INSERTED → ACCEPTED → ESCROW → COUNTED → VALIDATED → CONFIRMED
        → TRANSPORTING → STORED | REJECTED | RETURNED | JAMMED
 unresolved flows end in UNKNOWN_LOCATION
```

* States come from universal event codes (`CASH_INSERTED → INSERTED`,
  `CASH_ACCEPTED → ACCEPTED`, `CASH_ESCROWED → ESCROW`,
  `CASH_COUNTING_COMPLETED → COUNTED`, `VALIDATION_PASSED → VALIDATED`,
  `HOST_RESPONSE → CONFIRMED`, `CASH_STORED/REJECTED/RETURNED`, …).
  Models reach these codes through their own `events.yaml`; a model may
  extend the mapping via `cash.lifecycle_overrides`.
* `TRANSPORTING` is **inferred** (confidence 0.7) when a configured
  transport motor starts while cash is held; direct mappings carry
  confidence 1.0.
* Note metadata (denomination, serial, position, …) is extracted **only
  where the log carries it**; missing fields are the literal string
  `UNKNOWN` — never guessed. `note_id` stays `None` unless the log
  identifies the note.

## 3. Hardware correlation

* **Sensors** — every transition recorded with previous → new state. When
  a transport expectation existed, `expected_state`/`actual_state` are
  attached; a transition that fulfills a *missed* expectation after the
  run ended gets `abnormal_duration_ms`.
* **Motors** — start/stop pairing per motor name; a run is `timed_out`
  when it exceeds its configured `timeout_ms` or no stop is ever
  observed (a stop is never invented). Sensor transitions during the run
  are associated with it.
* **Gates/shutters** — command vs. position within
  `transition_timeout_ms`: `state_mismatch` (observed ≠ commanded),
  `timed_out` (position never observed → `actual_state = None`).
* **Transport** — configured transport motors plus their expected
  sensors; outcomes: `COMPLETED`, `TIMEOUT`,
  `MISSING_SENSOR_TRANSITION`, `REPEATED_MOVEMENT`,
  `UNEXPECTED_STATE`, `UNKNOWN`.

## 4. Jam classification — evidence combinations, never one error code

| classification | requires |
|---|---|
| `CONFIRMED_JAM` | explicit jam indication **and** independent corroboration (transport timeout, missing sensor transition, motor timeout, unexpected state, gate/shutter anomaly) |
| `PROBABLE_JAM` | explicit jam indication alone, **or** transport timeout together with missing sensor transition |
| `POSSIBLE_JAM` | a single anomaly (motor timeout, repeated movement, unexpected sensor state, gate/shutter mismatch or timeout, transport timeout alone) |
| `NO_EVIDENCE_OF_JAM` | cash reached a terminal state and no anomaly was observed |
| `INSUFFICIENT_DATA` | no cash-transport evidence, or cash mid-flow with no anomaly — a jam can be neither confirmed nor excluded |

## 5. Wording rules (no unsupported conclusions)

Statements contain observed facts and hedged hypotheses. Examples:

> ✅ "Motor STAKER exceeded its 8000 ms timeout (ran 25000 ms). This is
> consistent with a possible transport obstruction or another
> transport-related problem, but it is not sufficient to confirm a jam."

> ❌ never: "Motor is damaged."

Root-cause attribution is explicitly out of scope; CONFIRMED_JAM
statements state that "the available logs do not identify a
component-level root cause".

## 6. Temporal correlation

For each assessment the evidence window around the first anomaly is
configurable per model **and per device** (`hardware.yaml →
temporal_analysis`): defaults `before_seconds: 30`, `after_seconds: 60`;
e.g. P2800N widens the window around the TRANSPORT subject to 45 s/90 s.
Every event inside the window becomes part of the stored evidence list
(kind, timestamp, file id, line number, raw text).

## 7. API

`GET /api/transactions/{id}/hardware` →

```json
{
  "transaction": {…},
  "final_cash_state": "STORED | JAMMED | UNKNOWN_LOCATION | …",
  "cash_movements": […],       // each with file id + line + raw text
  "sensor_events": […], "motor_events": […],
  "gate_events": […], "shutter_events": […],
  "transport_events": […],
  "faults": [{ "classification", "subject", "statement", "evidence", "analysis_window" }],
  "timeline": [ { "timestamp", "kind", "event", "detail", "raw" } ]  // transaction + cash + sensor + motor + gate + shutter + transport + fault, chronological
}
```

## 8. Test matrix

`backend/tests/test_cash_lifecycle.py` (7), `test_jam_classifier.py`
(8), `test_hardware_api.py` (14) — covering: normal transport, sensor
timeout, transport timeout, possible jam, confirmed jam, sensor
mismatch, motor timeout, gate mismatch, shutter unknown, single-error-
code-is-not-a-confirmed-jam, merged timeline ordering, unknown-id error
envelope — for **both** P2800N and P2600N through the same engine.
