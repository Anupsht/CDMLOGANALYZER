# Model integrations — P2600N, P2800N & P2600L

How the three integrated CDM models flow through the universal engine
(Upload → Model Detection → Adapter → Parser → Normalized Events →
Transaction Correlation), what is **confirmed vs. assumed**, and how to
replace the assumptions with real evidence **without touching the engine**.

---

## 1. The universal path (identical for every model)

```
upload (file/ZIP)
  → model detection        model_registry + adapter.detect()      [config/models/<code>/model.yaml]
  → source detection       detection_service + adapter.detect_source()
                           (adapter filename patterns outrank generic rules)
  → parsing                adapter-scoped parser from log_sources.yaml
  → normalization          events.yaml + errors.yaml → universal event codes
  → correlation            correlator + model.yaml correlation rules
  → reconstruction         universal 9-stage lifecycle → transactions tables
```

Neither the pipeline, the correlator, the normalizer nor the reconstructor
contain a single model-code branch. Adding P2800N (Phase 3) required **zero
changes** to the universal transaction engine — proof is
`backend/tests/test_model_comparison.py`, which asserts a P2600N and a
P2800N transaction produce the same structure, stage vocabulary, status
values and confidence semantics.

## 2. ⚠️ SYNTHETIC evidence — read this first

**No real P2600N or P2800N log files were available** when these
integrations were written (announced samples never arrived). Therefore:

* **Line formats, field names, tokens, error codes and correlation keys
  are SYNTHETIC** — inferred from file names and generic CDM domain
  conventions only (e.g. `tid=`, `sess=`, `J|seq|`, `href=`, `rc=41`,
  `TRX|OPEN`). They are *plausible*, not *confirmed*.
* Every YAML file under `config/models/p2600n/`, `config/models/p2800n/`
  and `config/models/p2600l/` carries an explicit `SYNTHETIC` warning
  comment.
* Test fixtures under `backend/tests/fixtures/{p2600n,p2800n,p2600l}/` are
  synthetic log files labeled in `tests/fixtures/README-SYNTHETIC.md`.

The architecture is built so this costs nothing to fix: **replacing the
assumptions is a YAML-and-fixtures change, never a code change.**

## 3. YAML-only replacement path (real logs arrive — what to do)

1. **Update line formats** — for each source in
   `config/models/<code>/log_sources.yaml`, adjust `line_pattern`,
   `timestamp_format`, `content_signatures`, `filename_patterns` to the
   real format. No parser code changes; the generic line parser is
   config-driven (`backend/app/parsers/configured.py`).
2. **Update event mapping** — `config/models/<code>/events.yaml` patterns
   to the real message vocabulary. First match wins; anything unmatched
   stays `UNMAPPED` (visible in the timeline, never dropped).
3. **Update error catalogue** — `config/models/<code>/errors.yaml` with
   real codes; `$1`–`$9` substitute regex capture groups into codes
   (e.g. `code: P28IFM-$1` for `rc=(41|42|43)`).
4. **Update correlation keys** — `config/models/<code>/model.yaml`
   (`correlation.primary_key`, `rules[].key/weight/window_seconds`) and the
   `key_extract` patterns in `log_sources.yaml`. Keys, weights and windows
   are data.
5. **Update hardware extraction** — `config/models/<code>/hardware.yaml`
   (Phase 4): sensor/motor/gate/shutter line patterns, transport motor
   names, timeouts, expected sensors, jam indications, temporal windows,
   note extraction. See [hardware-analysis.md](hardware-analysis.md).
6. **Replace fixtures** — drop real sanitized samples into
   `backend/tests/fixtures/<code>/` (keep the same scenario matrix: success,
   host-declined, incomplete, malformed line, orphan line) and update
   `README-SYNTHETIC.md`.
7. Run `pytest` — the whole suite must stay green. If a test encoded a
   synthetic assumption that real logs disprove, fix the *fixture/YAML*,
   not the engine.

The same path applies to P2600L: its package was written SYNTHETIC
(distinct sources `apl`/`jal`/`dgn`, `P26L-*` error codes, `T-` transaction
ids) precisely so real logs can be swapped in without touching code. **No
P2600L pattern was inferred from P2600N** — the package is independent;
`test_model_framework.py` guards this (the P2600L package must not reuse
P2600N's source codes, signatures or error tokens).

## 4. P2600N — sources, mappings, assumptions

Sources (from the Phase-2 file inventory — file names confirmed, formats
synthetic):

| source | file | assumed format | events |
|---|---|---|---|
| `ecat` | `eCAT20260703.txt` | `YYYY-MM-DD HH:MM:SS \|eCAT\|MSG\|…` | START/COMPLETED/CASH_INSERTED/CASH_ACCEPTED/CASH_STORED |
| `cim` | `CIM30_2026-07-03.txt` | text lines with module tokens | VALIDATION_PASSED/FAILED, DEVICE_UNAVAILABLE |
| `keeper` | `Keeper20260703.txt` | `ERROR EC-nnnn …` style | ERROR (+`EC-$1` code), SENSOR_CHANGED |
| `jou` | `JOU20260703.txt` | `JRN nnn …` | counting/storage confirmations |
| `noteinfo` | `NoteInfo_31(…).csv` | CSV | CASH_INSERTED detail |

Correlation: `primary_key: txn_id`, rules `txn_id_exact` (1.0),
`session_window` (`session_id`, 0.6 @ **300 s**), `journal_seq` (0.5 @ 600 s),
`host_reference` (0.7).

**Unknowns deliberately marked:** Keeper `EC-` catalogue meanings are not
confirmed (codes captured verbatim); any CSV column whose semantics could
not be inferred maps to `UNKNOWN`/`UNMAPPED`.

## 5. P2800N — sources, mappings, assumptions

Sources (SYNTHETIC export naming: `P2800N_APP_*.log`, `P2800N_JRN_*.txt`,
`P2800N_SIU_*.log`, `IFM_*.log`):

| source | assumed format | events |
|---|---|---|
| `app` | `<ts>\|APP\|LEVEL\|MSG` pipe log | TRX\|OPEN→START, ESCROW_IN→CASH_ACCEPTED, NOTES_*→counting/validation/storage, TRX\|CLOSE\|OK→COMPLETED, TRX\|CLOSE\|FAIL→FAILED |
| `jrn` | `J\|seq\|ts\|tid\|amount\|CUR\|STATUS` | `|OK`→CASH_STORED, `|NOK|FAIL`→FAILED, `|CANCEL`→CASH_RETURNED |
| `siu` | `ts SIU msg` | device_unavailable→DEVICE_UNAVAILABLE, sensor_mask→SENSOR_CHANGED |
| `ifm` | `[ts] IFM REQ/RSP tid=… href=… rc=…` | REQ→HOST_REQUEST, rc=00→HOST_RESPONSE, rc=41/42/43→HOST_DECLINED (+`P28IFM-$1`) |

P2800N intentionally has **no Keeper/NoteInfo sources** — absence is
per-source-of-truth, not omission.

Correlation: `primary_key: txn_id`, rules `txn_id_exact` (1.0),
`session_window` (`session_id`, 0.6 @ **240 s**), `journal_sequence`
(0.5 @ 600 s), `host_reference` (0.7).

**Unknowns deliberately marked:** `rc` values other than 00/41/42/43 are
not interpreted (captured verbatim as `P28IFM-<rc>` with severity INFO and
description "interpretation pending vendor table"); the `E-99`-style app
error catalogue is unknown (`P28APP-<code>` verbatim).

Filename-pattern note (applies to any model): regex `\b` never matches
before/after `_` (underscore is a word character), so source tokens in
filenames like `IFM_20260703.log` must use `(?:^|[^a-z0-9])ifm(?:$|[^a-z0-9])`
semantics — this bit the P2800N `siu`/`ifm` patterns and is documented here
so it isn't reintroduced.

## 5b. P2600L — sources, mappings, assumptions (Phase 6)

Sources (SYNTHETIC; no real P2600L material was received — nothing was
inferred from P2600N, the sources and tokens are its own):

| source | assumed format | events |
|---|---|---|
| `apl` | `ts \| P2600L \| seq \| EVENT \| k=v…` application log | TRX OPEN→START, NOTES IN→CASH_INSERTED, NOTES TAKEN→CASH_ACCEPTED, NOTES OUT→CASH_RETURNED, COUNT DONE→counting, CHECK OK/FAIL→validation, HST REQ/RSP→host, BOX→CASH_STORED, TRX END OK→COMPLETED / FAIL→FAILED, jam→CASH_JAM_SUSPECTED |
| `jal` | `#seq\|ts\|T-…\|IN/OUT\|amount\|CUR\|STATUS` journal | IN/OUT confirmations, status OK/NOK/CANCEL |
| `dgn` | `ts DIAG comp=… msg` diagnostics | MOT (motor), SN (sensor 1→0 edges), GATE, E-402/E-n error codes, `jam detected` |

Correlation: `primary_key: txn_id`, rules `txn_id_exact` (1.0),
`journal_seq` (`#seq`, 0.5 @ 600 s), `session_id` (0.6 @ 240 s); `key_extract`
patterns per source (`hst=`, `#seq`, `sess=`).

Hardware (Phase 4 schema, in `hardware.yaml`): sensors `SN*`, motors `MOT*`,
gates `GATE*` with `expected_state_map`, transport trigger sensor `3`, motor
timeouts and jam indications — **no shutters by design** (the P2600L package
does not define them; absence is per-source-of-truth, not omission).

Error catalogue: `P26L-APL-*` (application), `P26L-HW-*` (hardware),
`UNK-P26L-FATAL` (unmapped fatal verbatim). Detection identifiers:
`P2600L FW`, `P2600L core` (software), `\bP2600L\b` + `p[-_]2600[-_]l`
(filename).

## 6. Universal event vocabulary & reconstruction

33 universal event codes (`backend/app/analysis/events.py`) — all models
normalize into the *same* vocabulary. The reconstructor evaluates the
9-stage lifecycle (`start, cash_insertion, cash_acceptance, counting,
validation, host_request, host_response, storage_or_return, final_status`)
for every transaction; stages with no confirming event are reported
`NOT_CONFIRMED` (marker entries with `raw=None`) — **never invented**.
Status precedence: DECLINED > FAILED > COMPLETED > INCOMPLETE.

The timeline API (`GET /api/transactions/{id}/timeline`) returns
chronological entries (timestamp, event, stage, device, severity, source,
detail, raw evidence: file id + line number + raw text) plus
`stages_confirmed` / `stages_not_confirmed` / `complete`.

## 7. Adding a fourth model — exact procedure

Everything below is additive; **no file under `app/analysis/`, the pipeline,
correlator or API routing changes**. Runtime pluggability is proven by
`test_model_framework.py::test_register_and_detect_runtime_model` (registers
a throwaway `P9999X` through the public API, detects it, pops it).

1. **Model directory** — `config/models/<code>/` with the seven YAML files:
   `model.yaml` (flat: identity `code/name/vendor`, `detection`
   filename_patterns + software_identifiers, `correlation` rules with
   weights/windows, `key_extract`), `log_sources.yaml` (one entry per
   source: filename_patterns, content_signatures, `line_pattern` or
   `type: csv` parser config, `key_extract`), `events.yaml` (regex →
   universal event codes, first match wins), `errors.yaml` (regex →
   `PREFIX-*` codes, `$1`–`$9` capture substitution), `devices.yaml`
   (device names/aliases — feeds detection + timeline device labels),
   `hardware.yaml` (sensors/motors/gates/shutters/transport/temporal —
   only what the model actually has), `diagnostics.yaml` (reconciliation
   rules overlay; universal rules come from `config/diagnostics/rules.yaml`
   automatically).
2. **Adapter** — `backend/app/adapters/<code>.py`: subclass
   `BaseModelAdapter`, set `model_code`, `filename_patterns`,
   `content_patterns`, call `register_adapter(<code>, <Class>)` at import;
   the detection/scoring/source logic itself is inherited and generic.
3. **Import registration** — the module must be imported at startup
   (already covered: `app/adapters/__init__.py` imports all adapter
   modules; add yours to that list if it doesn't auto-discover).
4. **Seed/reference data** — add the model row in
   `backend/app/database/init_db.py` (`active`, `placeholder: False`)
   so `/api/models` lists it.
5. **Parsers** — only if the format is not expressible with the generic
   line/CSV parsers: add a parser class and register it in
   `backend/app/parsers/registry.py`, then reference it by `type:` in
   `log_sources.yaml`. (All three current models use the generic parsers.)
6. **Mappings & rules** — covered by the YAML package in step 1; per-model
   diagnostic *rules* only via the model's `diagnostics.yaml` overlay.
   Never add model branches to `app/analysis/`.
7. **Tests** — `backend/tests/test_transactions_<code>.py` (auto-detection
   without model_code + evidence assertions, own-sources disjointness,
   golden scenarios: success/declined/failed, PARTIAL file, config
   endpoint) and a case in `test_model_framework.py`'s parametrized
   full-config-package check. Fixtures under
   `backend/tests/fixtures/<code>/` (SYNTHETIC-labeled unless real logs
   exist).
8. Run the full `pytest` suite — it must stay green without touching any
   other model's tests.

## 8. Test matrix (Phase 2–6, 171 tests green)

Per model: successful, host-declined, incomplete (+ error code), missing
log source, malformed line (file PARTIAL, correlation unaffected),
skewed timestamp outside window (not attached), auto-id for keyless
groups, orphan events never forced into transactions. Plus correlator
unit tests, cross-model structural-equality proofs
(`test_model_comparison.py`), Phase 4 hardware-fault goldens
(`test_hardware_*.py`), Phase 5 diagnostics goldens
(`test_diagnostics.py`: report/classification/failure classes/
reconciliation/requirement rules) and Phase 6 framework tests
(`test_model_framework.py`: registry plugin surface, ranked detection
with evidence, full-config-package ×3, not-inferred-from-P2600N guard,
config endpoint ×3; `test_transactions_p2600l.py`: P2600L end-to-end).
P2600L: T-8801 success → NORMAL_COMPLETION, T-8802 host-declined →
HOST_TRANSACTION_FAILURE, T-8803 failed+jam → CONFIRMED_CASH_JAM.
