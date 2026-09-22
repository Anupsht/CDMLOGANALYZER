# Database Guide

Schema, security and operations for the analyzer datastore.

## 1. Engines

* **Production**: MySQL 8 (`mysql+pymysql://user:pass@host:3306/cdm_analyzer?charset=utf8mb4`)
* **Development/tests**: SQLite (zero-setup; feature-identical via SQLAlchemy)

## 2. Schema map (by phase)

| Area | Tables |
|---|---|
| Foundation (P1) | `users`, `machine_models`, `machines`, `machine_components`, `log_sources`, `log_files`, `log_lines`, `parser_versions`, `model_configurations`, `audit_logs` |
| Transactions (P2–3) | `transactions`, `transaction_events` |
| Cash/hardware (P4) | `cash_movements`, `gate_events`, `motor_events`, `sensor_events`, `transport_events`, `fault_assessments` |
| Diagnostics (P5–6) | `diagnostic_findings`, `model_detections` |
| AI layer (P8) | `ai_explanations` |
| Patterns (P9) | `rule_suggestions` |
| Security (P10) | `users`(+password/lockout), `auth_sessions`, `cases`, `audit_logs`(+ip/result) |

`log_files.log_lines` is the immutable evidence backbone — parsed views
reference it; nothing writes back into it.

## 3. Security

* **Least privilege**: the application account gets
  `SELECT, INSERT, UPDATE, DELETE` on the app schema only. DDL (`CREATE/
  ALTER`) belongs to the migration account used by Alembic, not to the
  runtime account. No cross-database grants.
* **Credentials** come from environment (`CDM_DATABASE_URL`) — never in
  source, never committed. `.env` is git-ignored; `.env.example` documents
  every variable.
* **SQL injection**: all access flows through SQLAlchemy Core/ORM
  (parameterized statements). There is no string-built SQL in the codebase.
* **Sensitive data**: transaction amounts, serials and account-adjacent
  fields live in the DB; the AI digest deliberately excludes raw customer
  data, and unverified codes/serials/denominations are redacted before any
  external call.
* **Sessions**: `auth_sessions` stores only token *hashes*; a DB leak does
  not yield usable bearer tokens. Passwords are PBKDF2 hashes with
  per-user salts.

## 4. Migrations

```bash
cd backend
alembic upgrade head        # apply all pending
alembic current             # show applied revision
alembic downgrade -1        # revert last (rarely needed)
alembic history             # full chain
```

Chain (heads → base): `f2b8d3a71c04` (P10 security/RBAC) → `e7a41c92bf05`
(P9 rule suggestions) → `c3f8b62a91d4` (P8 AI) → … → `39b064dabb4b`
(initial). New tables also materialize via `create_all` in dev; **always
migrate in production**.

## 5. Backups & restore

```bash
# full backup (consistent, non-blocking with InnoDB)
mysqldump --single-transaction --routines --triggers --events \
  cdm_analyzer | gzip > cdm-$(date +%F).sql.gz

# restore
mysql -e "CREATE DATABASE cdm_analyzer CHARACTER SET utf8mb4"
gunzip -c cdm-2026-09-22.sql.gz | mysql cdm_analyzer
```

* Schedule daily dumps + offsite copies; keep 30 days.
* Back up `CDM_STORAGE_DIR` (uploads) and `config/` (model YAML) in the
  same window — a database without its raw logs loses the evidence chain.
* Test the restore path quarterly; time it and record the RTO.
* SQLite (dev): stop the API, copy the file (or use `VACUUM INTO`).

## 6. Housekeeping

* `audit_logs` is append-only; archive (`SELECT … INTO OUTFILE` → truncate
  window) rather than delete when it grows large.
* Orphaned extracted files (after a deleted upload) can be reconciled
  against `log_files.file_path` — originals under `uploads/original/` are
  the system of record.
