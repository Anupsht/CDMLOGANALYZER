# Diagnostic engine — root cause categories, rules & evidence (Phase 5)

How the system turns the Phase 2–4 evidence picture into structured,
hedged **findings** — with rules that are pure data.

## 1. Layering

```
Phase 2  normalized events (raw evidence pointers)
Phase 3  correlated transactions
Phase 4  cash lifecycle + hardware records + jam classification
Phase 5  THIS: data-driven diagnostic rules → findings
```

The engine (`backend/app/analysis/diagnostics.py`) contains **no
model-specific and no hard-coded diagnostic logic**. Rules, requirements
and reconciliation checks are data:

* `config/diagnostics/rules.yaml` — universal rules (apply to every model)
* `config/models/<code>/diagnostics.yaml` — optional per-model overlay:
  same rule/requirement id **replaces**, a new id **appends**; carries the
  model-specific reconciliation extraction patterns.

## 2. Rule conditions (all data)

| operator | matches |
|---|---|
| `event` / `any_event` | universal event code(s) (`any_event` also looks at subsequent transactions — recovery detection) |
| `sequence` + `window_seconds` | ordered event subsequence within the window |
| `device` | events on a named device |
| `sensor_anomaly` / `motor_timeout` / `gate_anomaly` / `shutter_anomaly` | Phase 4 hardware records |
| `transport_outcome` | Phase 4 transport outcome(s) |
| `jam_classification` | Phase 4 jam classification(s) |
| `cash_state` / `cash_final_state` | cash lifecycle states reached / terminal state |
| `transaction_status` | universal transaction status |
| `host_state` | `NO_REQUEST / NO_RESPONSE / APPROVED / DECLINED` (derived) |
| `error_code_prefix` / `error_code_any` | error codes captured on events |
| `reconciliation` | reconciliation issue name(s) |
| `all` / `any` / `exclude` | boolean combinators (nestable) |

## 3. Root cause categories & failure classes

Categories (per finding): `HARDWARE SOFTWARE FIRMWARE CONFIGURATION HOST
NETWORK COMMUNICATION SENSOR MOTOR GATE SHUTTER TRANSPORT CASH_HANDLING
UNKNOWN`.

Failure classes (the engine distinguishes): `HOST_FAILURE,
HARDWARE_FAILURE, COMMUNICATION_FAILURE, APPLICATION_FAILURE,
CASH_EXCEPTION` — plus `REQUIREMENT_VIOLATION`, `NO_FAILURE`,
`INSUFFICIENT_DATA` at report level. Example: cash accepted → counted →
host declined → cash returned = **HOST_TRANSACTION_FAILURE**
(`HOST_FAILURE`), explicitly **not** hardware.

## 4. Findings & evidence (sections 3–4)

Each finding carries: `finding_id, category, severity, confidence,
summary, interpretation, possible_causes, recommended_action, evidence,
cash_states`. Evidence refs point at normalized events, raw lines (file
id + line number + raw text), timestamps and devices; jam findings embed
the Phase 4 assessment's underlying raw-line refs, so a classification
always cites the actual log lines.

## 5. Confidence (section 5)

Levels `LOW → MODERATE → HIGH → VERY_HIGH`. A rule declares its base
level; the engine raises it **one step per threshold of independent
evidence sources** (event / cash / sensor / motor / gate / shutter /
transport / fault / reconciliation — flattened refs of one source count
once). Confidence is explicitly *not* certainty: interpretations are
hedged and possible_causes are hypotheses, never component-level root
causes ("consistent with a transport obstruction…", never "motor is
damaged").

## 6. Host vs hardware (section 7) & reconciliation (section 8)

`HOST_TRANSACTION_FAILURE` requires a host decline with cash accepted and
**returned**, and *excludes* every hardware anomaly signal — so a
healthy-transport decline never becomes a hardware finding.
`HOST_NO_RESPONSE` (request without response/decline) is a
`COMMUNICATION_FAILURE`. Reconciliation detects `ACCEPTED_NOT_STORED`,
`ACCEPTED_NOT_RETURNED`, `AMOUNT_MISMATCH`, `COUNT_MISMATCH` — a
comparison fires **only when both sides are present** (missing values are
never invented); amount/count extraction patterns are per-model data.
`HOST_CASH_OUTCOME_MISMATCH` and `TRANSACTION_OUTCOME_MISMATCH` catch
decision/outcome inconsistencies (application failure).

## 7. Requirement rules (section 9)

Configured under `requirements:` in the rules YAML — flagged **only when
configured**. Example shipped (disable by setting `enabled: false` or
removing the entry):

> "After a confirmed (or probable) cash jam, the machine must remain
> offline until manual intervention."

The trigger matches the Phase 4 jam classification; the violation looks
for activity of **subsequent transactions** (or an in-transaction
recovery signal) within `within_seconds` after the jam anchor (log time —
never analysis wall-clock). Violations produce a
`REQUIREMENT_VIOLATION` finding citing both the jam evidence and the
recovery events.

## 8. Output (section 10)

`GET /api/transactions/{id}/diagnostics` →

```json
{
  "transaction": {…},
  "summary": "2 finding(s); primary: CONFIRMED_CASH_JAM [HARDWARE_FAILURE, …]",
  "classification": "CONFIRMED_CASH_JAM",
  "diagnosis_class": "HARDWARE_FAILURE",
  "severity": "CRITICAL",
  "confidence": "VERY_HIGH",
  "final_cash_state": "JAMMED",
  "findings": [ { …, "evidence": […], "cash_states": […] } ]
}
```

The report is recomputed on read (cheap + deterministic), so rule changes
and late-correlated subsequent transactions are reflected immediately.

## 9. Golden test matrix (section 11)

`tests/test_diagnostics_engine.py` (14) — successful deposit, host
decline, cash exception, confirmed jam, possible jam (the section-6
"Possible transport obstruction" example verbatim), sensor issue,
automatic recovery (+ negative case), transaction mismatch, host/comm
distinction, amount-mismatch reconciliation (+ matching & missing-side
negatives), evidence structure. `tests/test_diagnostics_api.py` (10) —
end-to-end through upload/correlation on the Phase 4 fixture scenarios,
report recomputation and the config-driven proof (disabling a rule in
YAML changes the report).
