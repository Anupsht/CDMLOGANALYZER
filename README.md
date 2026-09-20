# Universal GRG CDM Log Analyzer

Production-grade log analysis platform for GRG Banking CDM (Cash Dispensing Module)
terminals — **P2600N**, **P2800N**, **P2600L** and future models.

> **Phase 1 — Foundation.** This repository currently implements the platform
> foundation: upload pipeline, safe ZIP extraction, immutable raw log storage,
> a parser framework, a model/plugin adapter architecture, MySQL persistence,
> background processing (Redis + Celery), a React dashboard, tests and docs.
> Model-specific transaction analysis (P2600N/P2800N), correlation, fault
> diagnosis and AI analysis are **deliberately not implemented yet** — see the
> roadmap below.

---

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
P2600N/P2800N, placeholder P2600L, log sources, parser registry).

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
    adapters/          BaseModelAdapter + P2600N/P2800N/P2600L placeholders
    tasks/             queue abstraction: Celery (Redis) or inline
    analysis/ rules/   reserved for Phase 2+ (empty by design)
  alembic/             migrations
  tests/               pytest suite (158 tests) + synthetic fixtures
frontend/              React + TypeScript + Tailwind dashboard
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
| 1 | Foundation (this repo) | ✅ done |
| 2 | Full P2600N/P2800N parsers, transaction & event models, correlation | planned |
| 3+ | Fault/cash-jam diagnosis, rules engine, AI analysis, reporting | planned |
