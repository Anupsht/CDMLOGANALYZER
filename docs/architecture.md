# Architecture

## Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            React + TypeScript                            │
│      Dashboard │ Logs (upload/drag-drop/progress/status) │ Models │      │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │ /api (proxied: vite dev / nginx)
┌──────────────────────────────▼───────────────────────────────────────────┐
│                              FastAPI backend                             │
│  ┌────────────┐  ┌───────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ middleware │→ │ error handling│→ │   API v1     │  │ OpenAPI docs  │  │
│  │ request-id │  │ clean envelope│  │ logs/models/ │  │   /docs       │  │
│  │ + timing   │  │               │  │ machines     │  │               │  │
│  └────────────┘  └───────────────┘  └──────┬───────┘  └───────────────┘  │
│                                            │                             │
│  ┌─────────────────────────────────────────▼──────────────────────────┐  │
│  │                     services (business logic)                      │  │
│  │  upload_service  zip_service(SafeZip)  detection_service           │  │
│  │  machine_service audit_service       pipeline                      │  │
│  └───────┬─────────────────────┬──────────────────────┬──────────────┘  │
│          │                     │                      │                 │
│  ┌───────▼───────┐   ┌─────────▼────────┐   ┌─────────▼──────────────┐  │
│  │ model registry│   │ parser framework │   │ task queue abstraction │  │
│  │ P2600N/P2800N │   │ BaseParser +     │   │ Celery+Redis  │ inline │  │
│  │ /P2600L       │   │ GenericText      │   └─────────┬──────────────┘  │
│  └───────────────┘   └──────────────────┘             │                 │
│          │                     │                      │                 │
│  ┌────────▼─────────────────────▼──────────────────────▼──────────────┐  │
│  │                SQLAlchemy models / MySQL (+Alembic)                │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
     MySQL 8               Redis 7              filesystem
  (10 tables)           (Celery broker)      data/uploads/original/
                                             data/uploads/extracted/
```

## Layering rules

1. **API layer** (`app/api/`) never touches ORM models from the parser or
   adapter packages; it speaks Pydantic schemas and services.
2. **Services** (`app/services/`) contain business logic and are the only
   callers of models + storage + registries.
3. **Parsers** (`app/parsers/`) and **adapters** (`app/adapters/`) are
   plugins: they register themselves into their registries and are never
   imported directly by core code.
4. **No model-specific code in core.** All knowledge about P2600N /
   P2800N / P2600L lives in `app/adapters/`. Adding a model never requires
   touching `app/api`, `app/services`, or `app/models` (see
   [model-adapter-development.md](model-adapter-development.md)).

## Processing pipeline

Every upload flows through one pipeline (implemented in
`app/services/pipeline.py`, executed by a task):

```
UPLOAD ──► VALIDATE ──► STORE ──► EXTRACT ──► IDENTIFY FILES ──► IDENTIFY LOG SOURCE
                                                                │
        ┌───────────────────────────────────────────────────────┘
        ▼
  SELECT PARSER ──► PARSE ──► STORE RAW DATA
```

* **VALIDATE** — stored file exists, size matches, SHA-256 matches.
* **EXTRACT** — ZIPs only: `SafeZipExtractor` rejects traversal paths,
  enforces entry-count and uncompressed-size budgets (archive-bomb
  protection), preserves the original ZIP, and records each member as a
  child `log_files` row (`parent_file_id`, `original_path`, checksum).
* **IDENTIFY LOG SOURCE** — ordered rule chain (filename → content
  signatures → extension hints) produces `ecat | cim | keeper | jou |
  noteinfo | application | host | unknown` plus a confidence.
* **IDENTIFY MODEL** — enabled adapters are asked `detect(ctx)`; the best
  confidence wins (never hard-coded).
* **SELECT PARSER** — adapter-preferred parser first, then registered
  parsers by priority, then the `generic_text` fallback.
* **PARSE & STORE RAW** — lines are stored in `log_lines` in batches with
  their normalized preliminary structure. **Raw text is immutable.**

### Status lifecycle

```
UPLOADED → VALIDATING → EXTRACTING → IDENTIFYING → PARSING → COMPLETED | PARTIAL | FAILED
```

Status updates are committed per stage, so `GET /api/logs/{id}/status` shows
live progress (including per-child status for ZIPs). `PARTIAL` means the
upload was processed with recoverable problems (e.g. some lines failed to
parse); `FAILED` means the pipeline could not proceed.

## Background processing

`app/tasks/queue.py` defines a small `TaskQueue` abstraction:

| Mode | When | Behavior |
|---|---|---|
| `CeleryQueue` | `CDM_CELERY_BROKER_URL`/`CDM_REDIS_URL` set | `celery -A app.tasks.celery_app:celery worker` processes uploads (Compose runs this as the `worker` service) |
| `InlineQueue` | no Redis configured | ThreadPoolExecutor inside the API process — zero-dependency dev mode |
| eager | `CDM_TASK_EAGER=true` | synchronous execution — used by tests |

All modes run the **same** `run_pipeline()` implementation.

## Storage layout

```
data/
└── uploads/
    ├── original/<yyyy>/<mm>/<file_id>__<safe-name>   # uploads, never modified
    └── extracted/<file_id>__<safe-name>              # ZIP members, new ids
```

* Original files are written once and never mutated.
* `file_path` is relative to the storage root; `resolve()` refuses paths
  escaping the root.
* Extracted members get **fresh ids** — ZIP member names only serve as
  provenance metadata (`original_path`).

## Error handling & logging

* `app/core/errors.py` — one `AppError` hierarchy mapped to clean JSON
  envelopes; `RequestValidationError`, HTTP exceptions and unexpected
  exceptions all return the same shape. Stack traces only go to logs.
* `app/core/logging.py` — structured JSON logs with `timestamp`, `level`,
  `service`, `operation`, `request_id`, `error`, `duration_ms`. The
  `RequestContextMiddleware` assigns/propagates `X-Request-ID` and logs
  every request with its duration.

## Extensibility points (Phase 2+)

* `app/parsers/` — model parsers subclass `BaseParser`.
* `app/adapters/` — model adapters subclass `BaseModelAdapter`
  (`normalize_event()` is the Phase 2 entry point).
* `app/analysis/`, `app/rules/` — intentionally empty packages reserved for
  correlation / diagnosis / rule engines.
* Schema: `transactions`, `transaction_events`, `cash_movements`, `faults`,
  `sensor_events`, `motor_events` tables will reference `log_files` /
  `log_lines` rows for evidence tracing.
