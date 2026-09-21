# Universal GRG CDM Log Analyzer

Production-grade log analysis platform for GRG Banking CDM (Cash Dispensing Module)
terminals — **P2600N**, **P2800N**, **P2600L** and future models. Models
are plugins: each is a YAML config package + thin adapter, auto-detected
from filename/content/software/device evidence — the universal engine has
zero model branches.

## Technician dashboard (Phase 7)

- **Operations Dashboard** — fleet (total / online / offline), transaction
  totals, hardware errors, possible jams, cash exceptions, host failures —
  all evidence-based counters from `/api/dashboard/summary`.
- **Transaction Explorer** — server-side filters: date, time, machine,
  model, transaction ID, amount range, status, host result, cash state,
  error code, event code, device; sortable, paginated.
- **Transaction Details** — 12 sections: Transaction / Cash / Host /
  Hardware summaries, interactive Timeline (click any event → original log
  line), Cash Trace (STORED/RETURNED/REJECTED/UNKNOWN classification),
  Errors, Sensors, Motors, Analysis (rules-engine report), Evidence (every
  raw line, jump-to-file-and-line), Recommendations, JSON/print export.
- **Machine Health** — per-machine failure rate, jam frequency, hardware
  errors, sensor abnormalities, device-unavailable and reset/recovery
  events + a *configurable heuristic score* (weights adjustable; the score
  is a triage aid, never presented as a diagnosis).
- **Log Viewer** — virtualized raw-line display (server-side windowed
  fetching), server-side search, level/source/transaction filtering,
  timestamp & line navigation, context lines, jump-to-evidence.

See `docs/technician-dashboard.md` for the page-by-page reference.

## AI explanations & vendor reporting (Phase 8)

The deterministic analysis is never replaced — an **explanation layer**
(`backend/app/ai/`) composes per-transaction explanations from the
rules-engine results, optionally through an external OpenAI-compatible LLM
(`CDM_AI_BASE_URL`/`CDM_AI_API_KEY`; off by default, the deterministic
composer is used and labelled as such).

- Structured, bounded **AI digest** (never raw log files):
  `GET /api/transactions/{id}/ai-digest`
- Validated **explanation** with the epistemic labels CONFIRMED / PROBABLE /
  POSSIBLE / UNKNOWN and an anti-invention guard (unverified codes, serials
  and denominations are stripped and logged):
  `POST /api/transactions/{id}/ai-explanation`
- **Vendor escalation report** with full evidence traceability:
  `GET /api/transactions/{id}/vendor-report`
- Professional **PDF** (`…/report.pdf`, reportlab) and structured **Excel**
  (`…/report.xlsx`, openpyxl: Transaction Summary / Events / Cash Trace /
  Hardware Events / Errors / Analysis).

See `docs/ai-explanations.md`. In the UI: Transaction Details → **Vendor
Report** → Generate explanation → Export PDF / Export Excel.

> **Phase 1 — Foundation.** This repository currently implements the platform
> foundation: upload pipeline, safe ZIP extraction, immutable raw log storage,
> a parser framework, a model/plugin adapter architecture, MySQL persistence,
> background processing (Redis + Celery), a React dashboard, tests and docs.
> Model-specific transaction analysis (P2600N/P2800N), correlation, fault
> diagnosis and AI analysis are **deliberately not implemented yet** — see the
> roadmap below.

---

## Analytics, patterns & maintenance insights (Phase 9)

Historical analytics over everything already stored — transactions, failures,
errors, jams, sensor faults, cash exceptions, host failures, device-unavailable
events and automatic resets — plus cross-machine comparison and an advisory
pattern detector. **No new parsing**: everything aggregates the existing
evidence tables (`backend/app/services/analytics_service.py`,
`GET /api/analytics/*`).

- **Trends** per day/week/month (transactions, failures, jams, errors),
  `GET /api/analytics/trends?bucket=daily|weekly|monthly&window_days=90`
- **Error analytics**: occurrence counts, affected machines/models, first/last
  occurrence and the common preceding/following events per error code
- **Cross-machine comparison**: by machine, location, model and detected
  software/firmware version (`detection.version_patterns` per model config)
- **Maintenance insights**: machines whose jam / hardware-error / failure /
  sensor-abnormality rate is *increasing* are flagged WATCH / WARNING /
  HIGH_RISK vs a baseline window. These are **triage heuristics only** — the
  system never declares a component failed from them
- **Direct answers** (`GET /api/analytics/insights`): which machines have the
  most problems, which errors are increasing, which model has the highest
  failure rate, which faults commonly precede transaction failure, and which
  machines to investigate first
- **Pattern → Suggested Rule → Human Review → Approval → Production.** The
  detector proposes drafts only (`SUGGESTED_*`, `requires_human_review: true`,
  never auto-loaded); filing, reviewing, approving and rejecting happen through
  `GET/POST/PATCH /api/analytics/rule-suggestions` with a mandatory reviewer
  name, an audit trail, and engine isolation (approved drafts still only become
  production rules when a human copies them into the YAML package)

In the UI: **Analytics** page — key-question insights, trend charts, model
comparison, machine ranking, error frequency with event neighbours, jam trends,
maintenance flags and the rule-suggestion review workflow.

## Quick start (Docker Compose)

```bash
cp .env.example .env          # adjust if needed (defaults work out of the box)
docker compose up -d --build
```

| Service    | URL                          | Notes                          |
|------------|------------------------------|--------------------------------|
| Frontend   | http://localhost:5173        | React dashboard (nginx)        |
| Backend API| http://localhost:8000/docs   | FastAPI, OpenAPI docs built in |
| MySQL      | localhost:3306               | `cdm_analyzer` database        |
| Redis      | localhost:6379               | Celery broker                  |

The backend applies migrations/seeds reference data on startup (models
P2600N, P2800N and P2600L — all active, log sources, parser registry).

Then try it:

```bash
# upload a text log
curl -F "file=@my-ecat.log" http://localhost:8000/api/logs/upload

# upload a ZIP of logs
curl -F "file=@logs-bundle.zip" http://localhost:8000/api/logs/upload

# watch processing status
curl http://localhost:8000/api/logs
```

Or simply open http://localhost:5173 and drag & drop files on the **Logs** page.

## Local development (no Docker required)

The backend runs fine without MySQL/Redis: it falls back to SQLite storage and an
in-process queue.

```bash
# --- backend (terminal 1) ---
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export CDM_DATABASE_URL=sqlite:///./data/cdm_dev.sqlite3   # optional (default)
uvicorn app.main:app --reload --port 8000

# --- frontend (terminal 2) ---
cd frontend
npm install
npm run            # dev server on http://localhost:5173 (proxies /api to :8000)
```

Full details: [docs/setup.md](docs/setup.md).

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System architecture, processing pipeline, layering rules |
| [docs/database.md](docs/database.md) | Schema, tables, relationships, migration strategy |
| [docs/parser-development.md](docs/parser-development.md) | How to write/registered parsers, source detection rules |
| [docs/model-adapter-development.md](docs/model-adapter-development.md) | **How to add a new CDM model** (adapter + registry + seed) |
| [docs/model-integrations.md](docs/model-integrations.md) | P2600N/P2800N integrations: SYNTHETIC assumptions & the YAML-only replacement path |
| [docs/hardware-analysis.md](docs/hardware-analysis.md) | Phase 4 cash lifecycle, hardware correlation & jam classification |
| [docs/diagnostics.md](docs/diagnostics.md) | Phase 5 diagnostic rules, root-cause categories, findings & evidence engine |
| [docs/setup.md](docs/setup.md) | Environment variables, Docker, local dev, troubleshooting |

## Project structure

```
backend/               FastAPI application
  app/
    api/               HTTP endpoints (v1) + middleware
    core/              config, structured logging, errors, model registry
    database/          engine/session, base classes, bootstrap & seeding
    models/            SQLAlchemy ORM (10 Phase 1 tables)
    schemas/           Pydantic request/response contracts
    services/          upload, zip, detection, machine, audit, pipeline
    parsers/           BaseParser + registry + GenericTextParser
    adapters/          BaseModelAdapter + P2600N/P2800N/P2600L (plugin registry)
    tasks/             queue abstraction: Celery (Redis) or inline
    analysis/ rules/   reserved for Phase 2+ (empty by design)
  alembic/             migrations
  tests/               pytest suite (189 tests) + synthetic fixtures
frontend/              React + TypeScript + Tailwind technician dashboard
config/                per-model YAML packages (config/models/<code>/)
docker/                Dockerfiles + nginx config
docs/                  developer documentation
```

## API (Phase 1)

```
POST /api/logs/upload          upload .txt/.log/.csv/.json/.zip
GET  /api/logs                 list + filters (status, source, machine, role)
GET  /api/logs/{id}            file metadata
GET  /api/logs/{id}/status     live processing status (incl. ZIP children)
GET  /api/logs/{id}/lines      stored raw lines (evidence)
GET  /api/models               model registry
GET  /api/models/{code}        model detail
POST /api/models/{code}/enable|disable
GET  /api/machines             fleet list
POST /api/machines             register machine
GET  /api/machines/{id}        machine detail
GET  /api/transactions/{id}/diagnostics
                                Phase 5 evidence-driven diagnostic report:
                                findings (category, severity, confidence
                                LOW..VERY_HIGH, summary, interpretation,
                                possible causes, recommended action) from
                                data-driven rules; every finding cites raw
                                log evidence; host vs hardware vs
                                communication vs application classification
GET  /api/health               health + queue/database status
```

Every error is a clean envelope: `{"error": {"code", "message", "details"},
"request_id"}` — internal stack traces never reach clients (they are logged
with the same `request_id`).

## Running tests

```bash
cd backend
source .venv/bin/activate
pytest            # 134 tests: DB, upload, ZIP security, checksums, dedup,
                  # parser selection, model registry, detection, API, pipeline,
                  # correlator, P2600N + P2800N transactions, model comparison,
                  # cash lifecycle, hardware correlation, jam classification,
                  # diagnostic rules/findings golden cases (Phase 5)
```

Tests are self-contained (temporary SQLite + eager queue) — no MySQL/Redis needed.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: upload pipeline, parser framework, adapters, persistence, dashboard | ✅ done |
| 2 | Full P2600N/P2800N/P2600L parsers, transaction & event models, correlation | ✅ done |
| 3 | Fault diagnosis & cash-jam analysis (evidence-based, hedged) | ✅ done |
| 4 | Universal rules engine + per-model YAML overlays | ✅ done |
| 5 | Model packages as data (config/models/<model>/*.yaml) | ✅ done |
| 6 | Machine health scoring & history | ✅ done |
| 7 | Technician dashboard (transactions, timeline, health, audit) | ✅ done |
| 8 | AI explanations & vendor reporting (explanation layer only) | ✅ done |
| 9 | Historical analytics, pattern detection, cross-machine analysis, maintenance insights, rule suggestions | ✅ done |
