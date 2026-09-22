# Troubleshooting Guide

Symptom → cause → fix, for operators and technicians.

## Upload & processing

**Upload rejected: "File type … is not allowed"**
Only `.txt .log .csv .json .zip` are accepted. Re-export the bundle from the
machine; do not rename foreign files.

**Upload rejected: "not a valid ZIP archive (bad magic bytes)"**
The file claims `.zip` but isn't (partial download/renamed file).
Re-export; check free space on the machine.

**Status FAILED — "Unsafe relative path / forbidden file type / compression
ratio"**
The archive failed safety inspection (path traversal, executable member, or
zip-bomb ratio). Re-export on the machine — never try to "repair" a bundle
by hand.

**Status FAILED — parser error**
Check `status_message` on `GET /api/logs/{id}`; capture the raw export for
vendor escalation (via the Vendor Report) and open a case.

**Stuck in UPLOADED/PARSING**
Worker not running: `GET /api/readiness` → `workers` component; start the
Celery worker (`docker compose up -d worker`). Inline mode processes during
the upload request instead.

## Authentication

**401 `unauthorized` in the dashboard**
Session expired (8 h default) or was revoked (password change). Sign in
again.

**423 `account_locked`**
Five failed logins → 15-minute lock. Wait, or have an ADMIN reset the
password (Users page).

**Login works but every page 403s**
Your role lacks the permission (e.g. analytics needs ANALYST/SUPERVISOR/
ADMIN). Ask an ADMIN for a role change on the Users page.

**ADMIN locked out entirely**
Sign in as another ADMIN; or (last resort) run the bootstrap again on an
empty `users` table — the bootstrap only creates an admin when none is
active. Reset a password directly:
`POST /api/auth/users/{username}/reset-password`.

## Analysis & data

**Transactions missing for an upload**
Check the model binding (`model_code`/machine) used at upload; transactions
only correlate for recognized models. Re-upload with the correct model —
duplicates are detected per checksum, so a corrected upload of a *changed*
bundle is fine.

**"UNKNOWN" software versions in Analytics**
That model has no `version_patterns` configured (deliberate for P2800N).
Add patterns in the model package to enable version comparison.

**Maintenance flag looks alarming**
Flags WATCH/WARNING/HIGH_RISK are rate-increase triage hints, **not**
component-failure declarations. Verify physically; use the timeline and
diagnostics evidence before ordering parts.

**Pattern appears, but no rule suggestion exists**
Detection thresholds are conservative; file the suggestion manually from
the Analytics page ("File as rule suggestion") — it still requires human
review before it can ever reach production YAML.

## Reports

**report.pdf / report.xlsx fails**
Reportlab/openpyxl missing → `pip install -r requirements.txt` in the
serving environment. Excel starts with `PK`, PDF with `%PDF` — if a proxy
mangles downloads, check its buffering rules.

## Operations

**`/api/readiness` says degraded**
`database: down` → check DB connectivity/credentials. `redis: down` →
broker unreachable; uploads queue inline only when no Redis is configured —
fix Redis or expect delayed processing.

**429 responses**
Per-IP rate limit (auth 30/min, API 600/min). Behind a proxy set
`CDM_TRUST_PROXY_HEADERS=true`; raise limits via `CDM_RATE_LIMIT_*` if your
workforce shares one egress IP.

**Audit entries show actor "system"**
Background pipeline actions (parse/analyze) are system-attributed; only
API requests carry the signed-in actor.
