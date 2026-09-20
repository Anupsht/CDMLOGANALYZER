# Model adapter development guide — *how to add a new CDM model*

Adding a model (e.g. a future **P3400N**) requires **zero changes** to the
core: no API routes, no services, no schema edits. Everything goes through
the model registry.

## 1. Create the adapter

`backend/app/adapters/p3400n.py`:

```python
"""P3400N adapter."""
import re

from app.adapters.base import BaseModelAdapter, ModelDetection
from app.core.registry import model_registry
from app.parsers.base import FileContext

_FILENAME_RE = re.compile(r"(?:^|[^a-z0-9])p[-_]?3400[-_]?n", re.IGNORECASE)
_CONTENT_RE = re.compile(r"\bP3400N\b")


class P3400NAdapter(BaseModelAdapter):
    code = "P3400N"                       # stable model code (matches DB seed)
    display_name = "GRG P3400N"
    description = "GRG P3400N cash dispenser adapter."
    is_placeholder = False                # True = registered but not supported yet
    sort_order = 40                       # display/attempt order

    LOG_SOURCES = ["ecat", "cim", "keeper", "jou", "noteinfo"]

    def detect(self, ctx: FileContext) -> ModelDetection | None:
        # filename / ZIP inner path hint
        haystack = f"{ctx.filename} {ctx.hints.get('original_path', '')}"
        if _FILENAME_RE.search(haystack):
            return ModelDetection(self.code, 0.6, "filename", "P3400N in name/path")
        # content signature fallback
        if _CONTENT_RE.search(ctx.head_text[:8192]):
            return ModelDetection(self.code, 0.5, "content", "P3400N token")
        return None

    def get_log_sources(self) -> list[str]:
        return list(self.LOG_SOURCES)     # sources this model may produce

    def get_parser(self, ctx: FileContext):
        # Phase 2: return your model parser instance here; return None to
        # fall back to the global parser registry (generic_text in Phase 1).
        return None

    def normalize_event(self, raw_event: dict):
        # Phase 2: map a raw parsed record to the model's canonical event.
        raise NotImplementedError("ships with model-specific analysis")


model_registry.register_model(P3400NAdapter.code, P3400NAdapter)
```

## 2. Export it

`backend/app/adapters/__init__.py` — importing the package triggers
registration:

```python
from app.adapters.p3400n import P3400NAdapter
```

## 3. Seed the DB row

Add to `MACHINE_MODELS` in `backend/app/database/init_db.py`:

```python
{
    "code": "P3400N",
    "name": "GRG P3400N",
    "description": "GRG P3400N cash dispenser.",
    "is_active": True,
    "is_placeholder": False,
},
```

Startup seeding is idempotent — in Docker, restart the backend (or run
`python -m app.database.init_db`) and the row appears.

That's it. The model now shows in `GET /api/models` and the Models page, can
be enabled/disabled (`POST /api/models/{code}/enable|disable` — mirrored to
`machine_models.is_active` and the in-process registry), participates in
model detection during the pipeline, and can be linked to machines.

## What the base adapter gives you

`BaseModelAdapter` (in `app/adapters/base.py`) defines the full contract:

| Method | Purpose | Phase 1 status |
|---|---|---|
| `detect(ctx)` | does this file belong to my model? | implemented per model |
| `get_model_info()` | metadata for registry/API | inherited |
| `get_log_sources()` | sources the model produces | implemented per model |
| `get_parser(ctx)` | nominate a parser for a file | `None` → registry fallback |
| `normalize_event(raw)` | canonical event mapping | `NotImplementedError` (Phase 2) |

## Testing checklist for a new model

1. `test_model_registry.py`-style tests: registration, enable/disable DB sync.
2. A detection test (filename + content signature paths).
3. An end-to-end test: upload a sample log ZIP → expect
   `machine_model_code` set on extracted children (see
   `test_pipeline.py::test_model_detected_from_zip_path`).

## Disabled vs placeholder models

* **Disabled** (`is_active=False`) — registered, detectable, toggleable;
  skipped during model detection in the pipeline.
* **Placeholder** (`is_placeholder=True`) — architecture marker only
  (P2600L today). Detection intentionally returns `None`; the UI badges it
  as *placeholder*.
