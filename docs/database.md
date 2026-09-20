# Database

MySQL 8 (utf8mb4) in production; SQLite for local dev/tests. All access goes
through SQLAlchemy 2.0 models in `backend/app/models/`.

## Migration strategy

* **Alembic** is the source of truth for upgrades (`backend/alembic/`).
  Docker entrypoint runs `python -m app.database.init_db --with-migrations`.
* `create_all` + idempotent seeding runs at every startup as a dev safety net.
* Generate new revisions from model changes:
  ```bash
  cd backend
  alembic revision --autogenerate -m "describe change"
  alembic upgrade head
  ```

## Tables (Phase 1)

```
users                  user accounts (auth arrives in a later phase)
machine_models         supported CDM model families (P2600N, P2800N, P2600L)
machines               physical devices, FK → machine_models
machine_components     dispenser/sensor/motor/... components,
                       FK → machines / machine_models (Phase 2 events attach here)

log_sources            registry of source types (ecat, cim, keeper, jou,
                       noteinfo, application, host, unknown)
log_files              uploads AND extracted ZIP members (file_role,
                       parent_file_id, original_path, checksum, status…)
log_lines              immutable raw line text + detected timestamp/level +
                       normalized preliminary structure

parser_versions        registered parsers + versions (generic_text@1.0.0)
model_configurations   JSON key/value config per machine model
audit_logs             append-only operation trail (actor, action, entity,
                       request_id)
```

### Relationships

```
machine_models 1──* machines 1──* machine_components
machine_models 1──* model_configurations
machine_models 1──* machines 1──* log_files
log_sources    1──* log_files 1──* log_lines
log_files      1──* log_files        (ZIP parent → extracted children)
log_files      ── log_files          (duplicate_of_id → first upload with same checksum)
```

### Key columns & constraints

* **UUID primary keys** (`CHAR(36)`, app-generated) everywhere except
  `log_lines` / `audit_logs`, which use auto-increment `BIGINT` (high volume).
* `created_at` / `updated_at` (server default `now()`, `ON UPDATE`) on all
  Phase 1 UUID tables.
* `log_files`: indexes on `checksum_sha256` (duplicate detection), `status`,
  `file_role`, `parent_file_id`, `machine_id`, `machine_model_id`,
  `log_source_id`; unique constraint `(log_file_id, line_number)` on
  `log_lines` guarantees stable line numbering.
* Status values are constrained app-side by
  `models.log_file.PROCESSING_STATUSES`
  (`UPLOADED, VALIDATING, EXTRACTING, IDENTIFYING, PARSING, COMPLETED,
  PARTIAL, FAILED`).

### Reference data (seeded, idempotent)

| Table | Rows |
|---|---|
| machine_models | P2600N (active), P2800N (active), P2600L (**placeholder, inactive**) |
| log_sources | ecat, cim, keeper, jou, noteinfo, application, host, unknown |
| parser_versions | generic_text @ 1.0.0 |
| model_configurations | `processing` key per model (`transaction_analysis.enabled = false`, planned Phase 2) |
| users | `system` service account |

## Future phases

The schema is designed so later phases **add** tables without altering the
Phase 1 core:

```
transactions        FK → log_files / machines / machine_models
transaction_events  FK → transactions, log_lines (evidence pointer)
cash_movements      FK → transactions, machine_components
faults              FK → machines, machine_components, log_lines
sensor_events       FK → machine_components, log_lines
motor_events        FK → machine_components, log_lines
```

Because every parsed line keeps its `raw_text` and `(log_file_id,
line_number)` coordinates, any future derived record can be traced back to
original evidence.

## MySQL DDL preview

The complete DDL compiled from the models (MySQL dialect) — regenerate with:

```bash
cd backend
python - <<'PY'
import app.models
from app.database.base import Base
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import mysql
for t in Base.metadata.sorted_tables:
    print(str(CreateTable(t).compile(dialect=mysql.dialect())), ";", sep="")
PY
```
