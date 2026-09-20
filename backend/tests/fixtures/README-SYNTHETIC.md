# ⚠️ SYNTHETIC FIXTURES — not real device logs

These files reproduce the **file inventory** of the log export provided by
the project owner on 2026-09-20 (same filenames/sources, dated 2026-07-03),
but their **line content is synthetic**: the sanitized real log contents
never reached the analyzer workspace (the attachment was lost between
sessions), and inventing "real-looking" content silently was explicitly
prohibited.

Consequently:

* Every pattern in `config/models/p2600n/*.yaml` and
  `config/models/p2800n/*.yaml` is a **documented template** marked
  SYNTHETIC.
* Fields whose semantics cannot be established from evidence are reported
  as `UNKNOWN` (uninterpretable) or `UNMAPPED` (structurally parsed, no
  event mapping) — by design, not by accident.
* When real sanitized logs arrive, only the YAML patterns (and these
  fixtures) need updating. **The universal engine, correlator, database
  and API do not change** — that is the Phase 3 architecture guarantee.

Fixture scenarios covered (both models):

| File | Scenario |
|---|---|
| `p2600n/` | 1 successful, 1 host-declined, 1 incomplete transaction across 6 sources |
| `p2800n/` | 1 successful, 1 host-declined, 1 incomplete transaction across 4 sources |
