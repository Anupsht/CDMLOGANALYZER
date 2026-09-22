# Model Adapter Guide

Adding a new CDM model family **without touching the core engine**.

## 1. Philosophy

The analysis core is universal and model-blind. Everything model-specific is
*data* in a YAML package:

```
config/models/<code>/
  model.yaml        # identity, detection, devices, events, versions
  parsers.yaml      # log-source → parser bindings
  events.yaml       # raw token → canonical event mappings
  hardware.yaml     # cash lifecycle / hardware stage rules
  diagnostics.yaml  # error codes → diagnostic overlays (Phase 5)
```

The adapter class itself is a thin shell that binds the package to the
registry — no business logic:

```python
# backend/app/adapters/p3000n.py
from app.core.registry import ModelAdapter, model_registry

class P3000NAdapter(ModelAdapter):
    model_code = "P3000N"
    config_package = "p3000n"

model_registry.register(P3000NAdapter)
```

## 2. Step by step

1. **Collect evidence**: sample export bundles per log source (eCAT/JOURNAL/
   SIU/IFM/…), plus any vendor documentation. Mark every inferred value
   `SYNTHETIC` in a comment until confirmed by owner documentation.
2. **Detect the source**: add filename patterns + software-identifier
   lines to `model.yaml → detection` so uploads land on the right parsers.
   Add `version_patterns` if firmware/software should be extracted for
   cross-machine analytics (regexes run over the first lines of each file).
3. **Map events**: fill `events.yaml` — raw log tokens map into the 33-code
   canonical vocabulary (`CASH_INSERTED … VALIDATION_FAILED`). Never invent
   events the machine cannot emit.
4. **Normalize devices**: declare cassettes/gates/motors/sensors with
   canonical ids so cross-machine comparison groups them correctly.
5. **Hardware rules**: `hardware.yaml` — stage confirmation and cash-state
   transitions; the jam classifier consumes these.
6. **Diagnostics overlay**: `diagnostics.yaml` — error-code → finding
   overlays with `evidence_requirements` (multi-source!). A lone error code
   must never auto-confirm a jam.
7. **Fixture + tests**: add `backend/tests/fixtures/<code>/` samples and a
   `test_transactions_<code>.py` (parse → correlate → analyze). Also extend
   the acceptance matrix in `tests/test_phase10_acceptance.py` so the model
   stays in the full-chain test.
8. **Seed the model row**: add the code/name to `MACHINE_MODELS` in
   `app/database/init_db.py`.

## 3. Checklist before merge

- [ ] No `if model_code ==` anywhere outside the adapter/config loader
- [ ] All inferred values marked `SYNTHETIC` (or replaced by owner docs)
- [ ] Unknown/undetectable values stay `UNKNOWN` — never fabricated
- [ ] Full test suite green, including the new model's chain
- [ ] Cross-machine analytics groups the model (versions, failure rate)

See `docs/model-adapter-development.md` for the field-level YAML reference
and `docs/model-integrations.md` for the existing P2600N/P2800N/P2600L notes.
