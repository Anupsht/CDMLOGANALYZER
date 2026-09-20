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
| log_sources | ecat, cim, keeper, jou, noteinfo, application, host, unknown (+ model sources `app`, created on demand) |
| parser_versions | generic_text @ 1.0.0 (+ configured model parsers, seeded from log_sources.yaml) |
| model_configurations | `processing` key per model |
| users | `system` service account |

## Transaction analysis (Phase 2/3)

```
transactions        FK → log_files (source_file_id) / machines / machine_models
                    transaction_id (raw), machine_id, model, start_time, end_time,
                    amount, currency, status, correlation_confidence,
                    correlation_method
transaction_events  FK → transactions, log_files (evidence pointer)
                    seq, event_code, stage, device, severity, timestamp,
                    source_code, model_code, log_file_id, line_number,
                    raw_text, detail (JSON)
```

* Rows are produced by the universal correlator + reconstructor from
  normalized events — never per-model code.
* Every `transaction_events` row keeps `(log_file_id, line_number,
  raw_text)`, so each reconstructed step is traceable to original evidence.
* Stages without confirming events are `NOT_CONFIRMED` markers
  (`raw=None`) — they are never invented.
* Migration: `e160ec93b2c1` (7 indexes on model/status/time/evidence FKs).

## Hardware & cash-flow analysis (Phase 4)

```
cash_movements      FK → transactions; from_state → to_state, timestamp,
                    device, evidence_event, confidence, note_info (JSON),
                    raw evidence pointer
sensor_events       FK → transactions; sensor, previous/new/expected/actual
                    state, abnormal_duration_ms, raw evidence pointer
motor_events        FK → transactions; start/stop, duration_ms, timeout_ms,
                    timed_out, transport_name, sensor_transitions (JSON)
gate_events         FK → transactions; gate|shutter command vs. position,
                    transition_ms, timed_out, state_mismatch
transport_events    FK → transactions; outcome (COMPLETED | TIMEOUT |
                    MISSING_SENSOR_TRANSITION | REPEATED_MOVEMENT |
                    UNEXPECTED_STATE | UNKNOWN)
fault_assessments   FK → transactions; classification (CONFIRMED_JAM |
                    PROBABLE_JAM | POSSIBLE_JAM | NO_EVIDENCE_OF_JAM |
                    INSUFFICIENT_DATA), hedged statement, evidence (JSON),
                    analysis_window (JSON)
```

Migration: `c7d21e5a8f40`. Every row that derives from a log line keeps
`(log_file_id, line_number, raw_text)` — diagnoses never exist without
inspectable evidence.

## Future phases

The schema is designed so later phases **add** tables without altering the
core:

```
rules / AI analysis / reporting tables (later phases)
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
