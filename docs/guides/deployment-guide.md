# Deployment Guide

## 1. Environments

| Mode | Database | Queue | Auth |
|---|---|---|---|
| Development | SQLite (`CDM_DATABASE_URL=sqlite:///./data/...`) | in-process inline | bootstrap ADMIN + demo users |
| Production | MySQL 8 | Redis + Celery worker | bootstrap ADMIN (change it), demo users **not** seeded |

## 2. Install (Docker Compose)

```bash
cp .env.example .env          # then edit — never commit .env
docker compose up -d --build
docker compose exec api alembic upgrade head
```

Services: `mysql`, `redis`, `api` (uvicorn), `worker` (celery), `web`
(nginx serving the built frontend and proxying `/api`).

## 3. Production checklist

- [ ] `CDM_ENVIRONMENT=production`, `CDM_DEBUG=false`
- [ ] Strong `MYSQL_ROOT_PASSWORD` / `MYSQL_PASSWORD`; DB account limited to
      the app schema (SELECT/INSERT/UPDATE/DELETE — no DDL in day-2 operation)
- [ ] `CDM_CORS_ORIGINS=https://your-dashboard.example` (never `*`)
- [ ] `CDM_BOOTSTRAP_ADMIN_PASSWORD` changed on first login; demo users disabled
- [ ] `CDM_REDIS_URL` + `CDM_CELERY_BROKER_URL` set; ≥1 worker running
- [ ] TLS terminated at the proxy; `CDM_TRUST_PROXY_HEADERS=true` if it sets
      `X-Forwarded-For`
- [ ] Rate limits reviewed (`CDM_RATE_LIMIT_*`)
- [ ] Backups scheduled (database + `CDM_STORAGE_DIR` + config) — see
      Administrator Guide §5
- [ ] Monitoring wired to `/healthz` (liveness) and `/api/readiness` (readiness)
- [ ] Secrets from a vault/secret manager, not in git

## 4. Migrations

Alembic is the only schema path in production:

```bash
cd backend && alembic upgrade head      # apply pending
alembic history --verbose | head        # inspect chain
```

The dev-time `create_all` shortcut never runs with
`CDM_ENVIRONMENT=production` semantics — always migrate.

## 5. Scaling notes

* API: uvicorn workers are stateless except the in-memory rate limiter —
  keep one process per rate-limit domain or move the limiter to Redis.
* Workers: scale Celery horizontally; uploads are queued per file.
* Storage: mount `CDM_STORAGE_DIR` on persistent volume; originals are
  immutable (never rewritten), so object storage sync (rsync/S3 mirror)
  is safe.

## 6. Rollback

```
docker compose pull && docker compose up -d          # previous tag
cd backend && alembic downgrade <previous-revision>  # only if a migration must be reverted
```

Raw uploads are never mutated by upgrades, so rollback is lossless for
evidence; DB downgrades only revert schema, never log data.
