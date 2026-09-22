# Administrator Guide

Operating the Universal GRG CDM Log Analyzer in production: accounts, roles,
audit, monitoring, and day-to-day administration.

## 1. Accounts & roles

Roles (least privilege — the backend `app/core/rbac.py` matrix is the single
source of truth):

| Role | Can |
|---|---|
| **ADMIN** | everything, incl. user administration, model enable/disable, audit |
| **TECHNICIAN** | upload logs, run analysis, open cases, generate reports |
| **SUPERVISOR** | review & approve rule suggestions, close cases, reports, analytics, audit |
| **ANALYST** | analytics, historical data, file rule suggestions |
| **VIEWER** | read-only |

The `service` account (seeded) is non-interactive and has **no** API
permissions.

### First login

On first startup the system bootstraps an `ADMIN` account (username
`admin`, password from `CDM_BOOTSTRAP_ADMIN_PASSWORD` — default
`Admin#12345`, development only). **Change this password immediately:**

1. Sign in → sidebar user chip → *Log out* is NOT the flow; use
   `POST /api/auth/change-password` (or the Users page → *Reset password*).
2. In development builds, demo accounts are also seeded
   (`technician/Tech#12345`, `supervisor/Super#12345`,
   `analyst/Analyst#12345`, `viewer/Viewer#12345`). Disable them in
   production via the Users page.

### Password policy

Minimum length (`CDM_PASSWORD_MIN_LENGTH`, default 10) plus at least one
uppercase letter, one lowercase letter and one digit. Passwords are stored
as salted **PBKDF2-HMAC-SHA256** hashes (default 200,000 iterations) —
plaintext is never stored or logged.

### Sessions & lockout

* Bearer session tokens; only their SHA-256 hash is stored server-side.
* Sessions expire after `CDM_SESSION_TTL_MINUTES` (default 480 = 8 h) and
  are revoked by logout, password change (all *other* sessions) or
  deactivation (all sessions).
* After `CDM_LOGIN_MAX_ATTEMPTS` (5) failed logins an account is locked for
  `CDM_LOGIN_LOCKOUT_MINUTES` (15). Every attempt — success or failure — is
  audited with the client IP.

### User administration

`GET/POST /api/auth/users`, `PATCH /api/auth/users/{id}`,
`POST /api/auth/users/{id}/reset-password` — all ADMIN-only, all audited.
ADMINs cannot demote or deactivate their own account.

## 2. Audit trail

Every security-relevant action records **actor, action, timestamp, resource,
IP, result** (`audit_logs` table): log uploads, machine/case creation,
analysis runs, report generations, rule-suggestion reviews, model
configuration changes, logins and failed logins, user administration.

Query it as ADMIN/SUPERVISOR:

```
GET /api/audit?action=auth.login_failed&limit=50
GET /api/audit?actor=technician&result=failure
```

The trail is append-only — there is no update or delete API.

## 3. Monitoring

* `GET /healthz` — process liveness (no dependencies).
* `GET /api/health` — API + database, queue mode.
* `GET /api/readiness` — component probe: `database`, `redis`
  (`not_configured` when unused), `workers` (inline queue or Celery broker
  reachability). Overall `status: degraded` when a critical component is down.

Wire your load balancer / orchestrator: liveness → `/healthz`,
readiness → `/api/readiness`.

## 4. Rate limiting & headers

* Security headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, minimal CSP) are always on.
* Per-IP fixed-window limits: `CDM_RATE_LIMIT_AUTH_PER_MINUTE` (30) for
  `/api/auth/*`, `CDM_RATE_LIMIT_API_PER_MINUTE` (600) elsewhere; `0`
  disables. Exceeded → `429 rate_limited`. Behind a reverse proxy set
  `CDM_TRUST_PROXY_HEADERS=true` so the real client IP is used.
* The in-memory limiter suits single-process deployments; run one API
  process per rate-limit domain or deploy a Redis-backed limiter when
  scaling out.

## 5. Backups (see also the Deployment & Database guides)

Daily:

```bash
# database
mysqldump --single-transaction --routines --triggers cdm_analyzer > backup-$(date +%F).sql
# raw log storage (immutable uploads + extracted members)
tar -czf storage-$(date +%F).tgz /var/lib/cdm/data/uploads
# configuration (model YAML packages, .env — keep offline & restricted)
tar -czf config-$(date +%F).tgz /opt/cdm/config /opt/cdm/.env
```

Restore: recreate the DB, apply dumps, `alembic upgrade head`, unpack storage
into `CDM_STORAGE_DIR`, restart. Test restores quarterly.
