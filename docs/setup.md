# Setup guide

## Requirements

* Docker + Docker Compose **(production-style run)**, *or*
* Python 3.11+, Node 22+, npm **(local dev)** — MySQL/Redis optional

## 1. Docker Compose (recommended)

```bash
cp .env.example .env
docker compose up -d --build
```

* Backend: http://localhost:8000 (docs at `/docs`)
* Frontend: http://localhost:5173
* MySQL: localhost:3306 (`cdm` / `cdm_password`, db `cdm_analyzer`)
* Redis: localhost:6379

Services: `mysql`, `redis`, `backend` (API), `worker` (Celery), `frontend`
(nginx serving the built SPA and proxying `/api`).

Useful commands:

```bash
docker compose logs -f backend        # structured JSON logs
docker compose exec mysql mysql -ucdm -pcdm_password cdm_analyzer
docker compose down -v                # full reset (drops data!)
```

## 2. Local development without Docker

No MySQL/Redis needed — the backend falls back to SQLite and an in-process
queue automatically.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173, /api proxied to :8000
```

Run the worker only if you configured Redis:

```bash
cd backend
celery -A app.tasks.celery_app:celery worker --loglevel=INFO
```

## 3. Configuration

All settings are environment variables with the `CDM_` prefix (see
`.env.example` for the full annotated list). Highlights:

| Variable | Default | Purpose |
|---|---|---|
| `CDM_DATABASE_URL` | `sqlite:///./data/cdm_dev.sqlite3` | SQLAlchemy URL. MySQL: `mysql+pymysql://user:pass@host:3306/cdm_analyzer?charset=utf8mb4` |
| `CDM_REDIS_URL` / `CDM_CELERY_BROKER_URL` | *(empty)* | enable Celery processing when set |
| `CDM_TASK_EAGER` | `false` | run pipeline synchronously (dev/tests) |
| `CDM_STORAGE_DIR` | `./data` | upload/extracted storage root |
| `CDM_MAX_UPLOAD_SIZE_MB` | `200` | upload limit |
| `CDM_MAX_EXTRACT_SIZE_MB` | `1024` | total uncompressed ZIP budget |
| `CDM_MAX_EXTRACT_FILES` | `500` | per-ZIP file count limit |
| `CDM_ALLOWED_UPLOAD_EXTENSIONS` | `.txt,.log,.csv,.json,.zip` | accepted uploads |
| `CDM_CORS_ORIGINS` | `*` | CORS allowlist |
| `CDM_LOG_LEVEL` / `CDM_LOG_FORMAT` | `INFO` / `json` | structured logging |

Priority: process env → `.env` in project root → built-in defaults.

## 4. Database migrations

```bash
cd backend
export CDM_DATABASE_URL=mysql+pymysql://...
alembic upgrade head          # apply
alembic revision --autogenerate -m "..."   # after model changes
```

Startup always runs idempotent seeding (machine models, log sources,
parser versions, default configuration).

## 5. Tests

```bash
cd backend
source .venv/bin/activate
pytest -v
```

Coverage includes: DB connection/tables, upload validation, duplicate
detection, checksum integrity, safe ZIP extraction, path-traversal and
archive-bomb rejection, parser selection, model registry, source detection,
API endpoints and the full pipeline status flow. Tests use isolated SQLite +
eager tasks — no services required.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `Backend not reachable` in the UI | API not running or proxy target wrong; check `http://localhost:8000/api/health` |
| Uploads stay `UPLOADED` | Worker not running (Redis mode) — check `docker compose logs worker`, or run without Redis for inline processing |
| MySQL connection refused (local) | Ensure MySQL is up and `CDM_DATABASE_URL` points to it; from *inside* Compose the host is `mysql`, not `localhost` |
| `413 file_too_large` | Raise `CDM_MAX_UPLOAD_SIZE_MB` |
| ZIP rejected as `archive_error` | Check for traversal paths / entry limits in the archive — rejection is intentional (safety) |
