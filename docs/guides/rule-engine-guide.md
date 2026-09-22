# Rule Engine Guide

The diagnostics rules engine (Phase 5+) and the human-in-the-loop rule
lifecycle (Phases 7/9).

## 1. How rules work

Rules are **data**, loaded from per-model YAML overlays
(`config/models/<model>/diagnostics.yaml`) on top of a universal engine
(`backend/app/analysis/diagnostics.py`):

```yaml
rules:
  - id: CONFIRMED_CASH_JAM
    when:
      all:
        - event: JAM_DETECTED
        - cash_state: [ESCROWED, UNKNOWN_LOCATION]
        - no_event: CASH_RETURNED
    then:
      diagnosis_class: CONFIRMED_CASH_JAM
      confidence: VERY_HIGH        # evidence strength, not certainty
      requires: [transport_error_or_sensor_or_state]   # multi-source evidence
```

Key invariants:

* **Confidence = evidence strength** — LOW / MODERATE / HIGH / VERY_HIGH.
* **Single error codes never confirm a jam** — rules require corroboration
  (transport errors, sensor changes, unresolved cash state).
* **Missing reconciliation sides are never a mismatch** — absence of data is
  INSUFFICIENT_DATA, not a fault.
* REQUIREMENT_VIOLATION only fires when the model package configures it;
  host / hardware / communication / application / cash-exception classes
  stay distinct.

## 2. Pattern → suggested rule (Phase 9 workflow)

The analytics detector (`GET /api/analytics/patterns`) finds repeated
errors, jam locations, time clusters, model-specific and denomination
patterns. Each pattern carries an **inert draft** (`SUGGESTED_*`,
`requires_human_review: true`, "Never auto-loaded" production note).

The workflow is strictly:

```
Pattern → Suggested Rule → Human Review → Approval → (manual) Production YAML
```

* `POST /api/analytics/rule-suggestions` — file a draft (ANALYST/SUPERVISOR/ADMIN)
* `PATCH …/{id}` with `reviewed_by` — UNDER_REVIEW → APPROVED / REJECTED /
  INCORPORATED (reviewer name mandatory; fully audited)
* **APPROVED ACTIVATES NOTHING.** The engine loads only YAML; a human copies
  an approved draft into the model package (and marks the suggestion
  INCORPORATED). Tests enforce the isolation
  (`DiagnosticConfig.load(None)` never contains `SUGGESTED_*`).

## 3. Incorporating an approved rule

1. Open the Analytics page → *Rule suggestions* (status APPROVED).
2. Copy the draft into `config/models/<model>/diagnostics.yaml`, adapting
   ids/thresholds to house style. Remove the `SUGGESTED_` prefix.
3. Add fixture evidence covering the new rule; extend engine tests.
4. `PATCH` the suggestion to INCORPORATED with a note referencing the
   config commit.

## 4. Tuning thresholds

Pattern detection thresholds live at the top of
`app/services/analytics_service.py` (`PATTERN_MIN_REPEATS`,
`PATTERN_TIME_SHARE`, `PATTERN_MODEL_SHARE`) and are deliberately
conservative — prefer missing a weak pattern over auto-suggesting noise.
Maintenance flags (`_FLAG_THRESHOLDS`) compare a recent window against a
baseline and only ever produce WATCH/WARNING/HIGH_RISK triage hints.
