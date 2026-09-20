# Parser development guide

Parsers convert raw log text into a normalized preliminary structure. Phase 1
ships only the framework + a generic fallback; model parsers (P2600N,
P2800N) follow in Phase 2 using exactly this interface.

## The interface

```python
from app.parsers.base import BaseParser, FileContext, ParsedLine, ParseResult

class MyParser(BaseParser):
    code = "p2600n_ecat"          # unique, stable, used in parser_versions
    version = "1.0.0"
    source_type = "ecat"          # targeted log source
    description = "P2600N E-CAT log parser"
    priority = 10                 # lower = tried earlier during selection

    def can_parse(self, ctx: FileContext) -> bool:
        """Cheap check (extension, head bytes). No disk re-reads needed:
        ctx.head_text contains the first 64 KB decoded."""

    def parse_line(self, raw_text: str, line_number: int) -> ParsedLine | None:
        """Parse ONE line. Return None to skip it.
        ParsedLine(line_number, raw_text, timestamp=None, level=None,
                   source=None, normalized={...})"""

    # parse_file() has a default implementation: streams the file and calls
    # parse_line per line, collecting errors without aborting. Override only
    # if you need multi-line records (e.g. stacked transaction blocks).
```

Contract rules:

* **Never modify the file.** Parsers only read.
* **Always fill `raw_text` verbatim** — it is the evidence trail.
* `normalized` is the *preliminary* structure; keep it JSON-serializable
  (stored in `log_lines.normalized_data`).
* One bad line must not kill the file — raise inside `parse_line` is caught
  and recorded in `ParseResult.errors` (file status becomes `PARTIAL`).

## Registering a parser

```python
from app.parsers.registry import parser_registry

parser_registry.register(MyParser)      # instance created for you
```

Registration is idempotent for the same class; a *different* class with the
same `code` raises `ValueError`. Load it from `app.main.lifespan` (or from a
model adapter, see below).

## Selection order

`parser_registry.select(ctx, preferred_codes)`:

1. Preferred codes (a model adapter may nominate a parser)
2. Registered parsers by `priority`
3. `generic_text` fallback (always registered last)

## Source detection (feeding the parser choice)

Detection answers *"which log source is this file?"*. Rules live in
`app/services/detection_service.py` and run in priority order:

| Rule | Signal | Example |
|---|---|---|
| `FilenameRule` (0.9) | filename / ZIP inner path | `ecat.log` → ecat |
| `ContentSignatureRule` (0.7) | regex over first 16 KB | `E-CAT` in head → ecat |
| `ExtensionRule` (0.2) | weak hint | `.log` → application |
| *(fallback)* | nothing matched | unknown |

Add a rule (e.g. a model-specific signature) at startup:

```python
from app.services.detection_service import ContentSignatureRule, detection_service

detection_service.register_rule(
    ContentSignatureRule({"ecat": [r"P2600N E-CAT session start"]}, confidence=0.95)
)
```

New source types should also be seeded into the `log_sources` table
(`app/database/init_db.py`) so they appear consistently in the API/UI.

## Registering parser versions in the DB

`parser_versions` tracks implementations over time (seeded in
`app/database/init_db.py::PARSERS`). When you add a parser, add a row there
so the API/DB reflect the active registry.

## Writing tests

See `backend/tests/test_parser_selection.py` and `test_pipeline.py` for the
patterns: selection order, timestamp/level extraction, raw-text preservation,
and end-to-end status flow through the API.
