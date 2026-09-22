# Parser Guide

Writing and maintaining log parsers.

## 1. Where parsers live

`backend/app/parsers/` — each parser is a small, focused class bound to a
log source by the model's `parsers.yaml`. The pipeline flow:

```
upload → safe ZIP extraction → source detection (per file)
       → parser selection (model package) → line parsing
       → normalization (canonical events) → correlation → analysis
```

## 2. Parser contract

A parser receives the decoded text of one file and yields structured
candidates:

* **Timestamps** — parse into naive UTC datetimes; the normalizer attaches
  them to events. Formats are declared per source (e.g. `%y%m%d%H%M%S`,
  `YYYY-MM-DD HH:MM:SS`).
* **Raw preservation** — keep the original line and its line number; the
  evidence chain (`file · line · timestamp · raw text`) is built from these
  and original files are never modified.
* **No interpretation** — parsers extract *tokens* (amounts, codes, device
  names, states); interpretation happens in normalization and analysis.
* **Missing data stays missing** — emit `UNKNOWN`/skip rather than guessing;
  downstream analytics deliberately surfaces UNKNOWNs (e.g. versions).

## 3. Adding a parser

1. Implement `Parser` (see existing `p2600n_*`, `p2600l_*` classes for the
   minimal surface).
2. Register in `app/parsers/registry.py` (`load_builtin_parsers`).
3. Bind it to a log source in the model package's `parsers.yaml`.
4. Add fixtures + tests: selection test (`test_parser_selection.py`
   pattern) and content assertions on parsed events.

## 4. Rules for robustness

* Log exports are messy: tolerate blank lines, BOMs, CRLF, wrapped lines.
* Anchor on stable tokens (module names, op codes) rather than prose.
* Never let one bad line abort the file: collect per-line errors; the
  pipeline reports counts, the status stays COMPLETED with warnings.
* Performance: streaming-friendly — the pipeline caps memory by reading
  members incrementally; avoid loading whole files repeatedly.

## 5. Testing a parser change

```bash
cd backend && .venv/bin/python -m pytest tests/test_parser_selection.py tests/test_correlator.py -q
```

Then run the model's transaction tests and the acceptance chain to catch
cross-model regressions.
