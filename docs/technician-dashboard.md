# Technician dashboard (Phase 7)

The web interface production technicians use to go from *a stack of logs* to
*an evidence-backed diagnosis*. It is a plain React + TypeScript + Tailwind
SPA (`frontend/`) served by Vite in development and nginx in production; the
browser only ever talks to the same origin (`/api` is proxied to the
backend), so it works unchanged locally and in sandboxed previews.

---

## 1. Pages & workflows

| Route | Page | What a technician does there |
|---|---|---|
| `/` | **Operations Dashboard** | Glance at fleet (total / online / offline) and transaction KPIs (total, successful, failed, hardware errors, possible jams, cash exceptions, host failures). Upload logs, open recent transactions. |
| `/transactions` | **Transaction Explorer** | Find transactions by date, time-of-day, machine, model, transaction ID, amount range, status, host result, cash state, error code, event code or device — every filter runs **server-side**. |
| `/transactions/:id` | **Transaction Details** | The full analysis: 12 sections (below), export to JSON or print. |
| `/health` | **Machine Health** | Per-machine failure rate, jam frequency, hardware errors, sensor abnormalities, device-unavailable events, reset/recovery events, plus a configurable heuristic score for triage. |
| `/logs` | **Logs** | Upload bundles, per-file status (COMPLETED / PARTIAL / FAILED), jump into the viewer. |
| `/logs/:fileId?line=N` | **Log Viewer** | Read the immutable raw lines: search, level/source filters, timestamp & line navigation, context lines, evidence jumps. |

### Transaction Details sections

Transaction Summary · Cash Summary · Host Summary · Hardware Summary ·
Timeline · Cash Trace · Errors · Sensors · Motors · Analysis · Evidence ·
Recommendations.

- **Timeline** — every entry is clickable and expands the **original log
  line** (file + line number + raw text) plus the normalized metadata, with
  a deep link into the Log Viewer. `NOT_CONFIRMED` lifecycle stages are
  rendered explicitly as markers without evidence — never styled as data.
- **Cash Trace** — one row per note movement: note id, denomination, state
  transition, timestamp, device, destination, confidence. Final states are
  classified STORED / RETURNED / REJECTED / UNKNOWN (display grouping; the
  underlying state text stays verbatim).
- **Analysis / Evidence / Recommendations** — the Phase-5 rules-engine
  report: findings with severity + confidence (LOW…VERY_HIGH — evidence
  strength, never certainty), possible causes labelled as hypotheses, and
  the aggregated raw-line evidence each finding rests on.

## 2. Health score — explicitly not a diagnosis

The backend exposes **raw counters only** (`GET /api/machines/{id}/health`).
The score is computed in the browser as

```
score = 100 × (1 − Σ component_stress × weight / Σ weights)
```

where components are per-transaction rates (failure rate, jam frequency,
hardware errors, sensor abnormalities, device-unavailable, reset/recovery)
and the weights are technician-adjustable sliders persisted in
`localStorage`. The UI always labels the score as a *heuristic
prioritisation aid*, and the API response carries the same disclaimer.

## 3. Performance (large datasets)

- **Server-side filtering + pagination** — transaction list and log-line
  queries filter/sort/paginate in SQL (`?date_from&time_from&amount_min&
  host_result&cash_state&error_code&device&event_code&sort&dir&limit&offset`).
- **Virtualized log display** — the viewer renders only the visible window
  (fixed 22 px rows) and fetches 400-line chunks on demand by absolute line
  number; a 100k-line file loads as fast as a 100-line one.
- **Lazy loading** — every heavy page is a `React.lazy` code-split chunk.
- Search runs server-side (`?q=` substring on raw text); matches are
  collected up to a cap, and jumping to a match recentres the virtual list
  with ±N context lines.

## 4. New backend surface added in Phase 7 (all generic, read-only)

| Endpoint | Purpose |
|---|---|
| `GET /api/dashboard/summary` | Fleet + transaction + finding counters (distinct-transaction counts reuse the Phase-5 classification stored in `diagnostic_findings`). |
| `GET /api/machines/{id}/health` | Raw per-machine health counters (no score). |
| `GET /api/transactions` (extended) | Server-side filters listed above; `host_result`/`cash_state` map to universal event-code predicates — stored data is never reinterpreted. |
| `GET /api/logs/{id}/lines` (extended) | `q`, `level`, `line_from`, `line_to`, `ts_from`, `ts_to` for the viewer. |

Also fixed: `devices.yaml` name templates now support `$1`–`$9` capture
substitution (e.g. P2600L `Motor-$1`, `Cassette-1`), matching the existing
event/error substitution behaviour.

## 5. Completion checklist (spec §10)

A technician can: **upload logs** (dashboard / logs page) → **find
transaction** (explorer filters) → **open transaction** (detail page) →
**see timeline** (clickable events with raw lines) → **trace cash** (cash
trace + state classification) → **inspect hardware** (sensors / motors /
faults) → **read diagnosis** (analysis section) → **open evidence** (raw
line + jump to file:line) → **export report** (JSON download / print).
