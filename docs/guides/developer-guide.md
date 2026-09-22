# Developer Guide

Architecture, conventions and workflows for contributing code.

## 1. Stack & layout

* **Backend**: FastAPI + SQLAlchemy 2 + Pydantic v2, Alembic migrations,
  Celery/Redis optional (inline queue fallback). `backend/app/`:
  * `api/v1/` routers · `services/` domain logic · `models/` ORM
  * `parsers/` + `core/registry.py` — plugin architecture
  * `core/` config, security, RBAC, hardening, errors, logging
  * `config/models/<model>/` — per-model YAML packages (data, not code)
* **Frontend**: React 18 + TypeScript + Vite + Tailwind 4,
  dependency-free SVG charts. `frontend/src/`.

## 2. Non-negotiable conventions

1. **No model-specific conditionals in universal engines.** All per-model
   behavior lives in `config/models/<model>/*.yaml` (Phase 5 discipline).
   Adding a CDM model must never require touching the analysis core.
2. **Evidence or it didn't happen.** Every diagnosis references
   file/line/timestamp/raw text; confidence = evidence strength
   (LOW/MODERATE/HIGH/VERY_HIGH); possible causes are hypotheses.
3. **Original logs are immutable.** Uploads are stored once (checksummed)
   and never modified; extraction happens to separate files.
4. **Deterministic analysis is never replaced.** The AI layer (Phase 8) only
   explains engine output, from bounded structured digests, with
   anti-invention guards.
5. **Patterns never auto-promote** to production rules (Phase 7/9 workflow:
   SUGGESTED → human review → APPROVED → manual YAML incorporation).
6. **No stack traces to users** — errors go through `app/core/errors.py`
   envelopes; unexpected exceptions log server-side, return `internal_error`.

## 3. Authentication & RBAC (Phase 10)

* Passwords: PBKDF2 via `app/core/security.py`; sessions: `auth_sessions`
  rows keyed by token SHA-256; expiry + revocation in
  `app/services/auth_service.py`.
* `get_current_user` (bearer) → `require_permission("perm")` dependency
  factories guard endpoints. Add new endpoints with the same pattern:
  router-level `Depends(get_current_user)` + per-endpoint permission.
* New permissions must be added to `PERMISSIONS` in `app/core/rbac.py` and
  mirrored in `frontend/src/auth.tsx` (UI hints only).

## 4. Testing

```bash
cd backend && .venv/bin/python -m pytest -q          # full suite (fast, SQLite)
cd frontend && npm run build                          # tsc --noEmit + vite
```

* Fixtures per model live in `backend/tests/fixtures/<model>/`.
* `client` fixture = authenticated-as-admin TestClient; `auth_client` =
  real login/RBAC path. Rate limits and hash iterations are disabled/cheap
  in tests via conftest env.
* Golden rule: **all tests green before completion**, including the
  per-model acceptance chain (`tests/test_phase10_acceptance.py`).

## 5. Adding a migration

```bash
cd backend && alembic revision -m "short description"
# edit upgrade()/downgrade(); models must match the final schema
```

Dev databases can be recreated from scratch; production only ever uses
`alembic upgrade head`.

## 6. Local development

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && uvicorn app.main:app --reload
cd frontend && npm ci && npm run dev        # proxies /api → :8000
```

See also: Parser Guide, Model Adapter Guide, Rule Engine Guide,
Database Guide for deeper dives.
