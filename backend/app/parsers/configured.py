"""Config-driven parsers.

These parsers are the workhorses for model integrations. They contain no
model-specific logic: every format detail (line regex, timestamp format,
CSV columns, extensions, content signatures) comes from the model's
``log_sources.yaml`` via :mod:`app.core.model_config`.

Two flavors:

* :class:`ConfiguredLineParser` — regex line logs (named groups:
  ``ts``, ``device``, ``level``, ``msg``; extra named groups land in
  ``normalized['fields']``).
* :class:`ConfiguredCsvParser` — header-based CSV logs (e.g. NoteInfo).

Malformed lines: a line that does not match the configured shape raises
inside ``parse_line``; :class:`~app.parsers.base.BaseParser.parse_file`
records the error (file → PARTIAL) and continues. Raw text is always
preserved verbatim.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any

from app.parsers.base import BaseParser, FileContext, ParsedLine


def _parse_timestamp(value: str, fmt: str) -> datetime | None:
    value = value.strip()
    candidates = [fmt] if "%f" in fmt else [fmt]
    # Tolerate missing fractional seconds when the format expects them.
    if "%f" in fmt:
        candidates.append(fmt.replace(".%f", "").replace(" %f", ""))
    for candidate in candidates:
        try:
            return datetime.strptime(value, candidate)
        except ValueError:
            continue
    return None


class ConfiguredLineParser(BaseParser):
    """Regex-based line parser defined entirely by YAML configuration."""

    kind = "line"

    def __init__(self, code: str, source_type: str, config: dict[str, Any], priority: int = 50) -> None:
        self.code = code
        self.source_type = source_type
        self.config = config
        self.priority = int(config.get("priority", priority))
        self.description = config.get("description", f"Configured line parser ({code})")
        self._line_re = re.compile(config["line_pattern"])
        self._ts_format = config.get("timestamp_format", "%Y-%m-%d %H:%M:%S")
        self._content_sigs = [re.compile(s, re.IGNORECASE) for s in config.get("content_signatures", [])]
        self._extensions = {e.lower() for e in config.get("extensions", [])}

    def can_parse(self, ctx: FileContext) -> bool:
        if self._extensions and ctx.extension not in self._extensions:
            return False
        if self._content_sigs:
            return any(sig.search(ctx.head_text[:16384]) for sig in self._content_sigs)
        return True

    def parse_line(self, raw_text: str, line_number: int) -> ParsedLine | None:
        match = self._line_re.match(raw_text)
        if match is None:
            raise ValueError("line does not match the configured format")
        groups = match.groupdict()
        timestamp = _parse_timestamp(groups.get("ts", ""), self._ts_format) if groups.get("ts") else None
        reserved = {"ts", "device", "level", "msg"}
        fields = {k: v for k, v in groups.items() if k not in reserved and v is not None}
        return ParsedLine(
            line_number=line_number,
            raw_text=raw_text,
            timestamp=timestamp,
            source=self.source_type,
            level=groups.get("level"),
            normalized={
                "msg": groups.get("msg") or "",
                "device": groups.get("device"),
                "fields": fields,
            },
        )


class ConfiguredCsvParser(BaseParser):
    """Header-based CSV parser defined entirely by YAML configuration."""

    kind = "csv"

    def __init__(self, code: str, source_type: str, config: dict[str, Any], priority: int = 50) -> None:
        self.code = code
        self.source_type = source_type
        self.config = config
        self.priority = int(config.get("priority", priority))
        self.description = config.get("description", f"Configured CSV parser ({code})")
        self._delimiter = config.get("delimiter", ",")
        self._header_sig = re.compile(config.get("header_signature", "."), re.IGNORECASE)
        self._ts_column = config.get("timestamp_column")
        self._ts_format = config.get("timestamp_format", "%Y-%m-%d %H:%M:%S")
        # column name → semantic field name (unmapped columns stay as-is)
        self._columns: dict[str, str] = config.get("columns", {})
        self._extensions = {e.lower() for e in config.get("extensions", ["csv"])}

    def can_parse(self, ctx: FileContext) -> bool:
        if self._extensions and ctx.extension not in self._extensions:
            return False
        first_line = ctx.head_text.splitlines()[0] if ctx.head_text.splitlines() else ""
        return bool(self._header_sig.search(first_line))

    def parse_line(self, raw_text: str, line_number: int) -> ParsedLine | None:
        row = next(csv.reader(io.StringIO(raw_text), delimiter=self._delimiter))
        if not row:
            raise ValueError("empty CSV row")
        header = self.config.get("_header")  # injected by parse_file override
        if header is None:
            # Without a cached header we cannot interpret the row reliably.
            raise ValueError("CSV header not yet established")
        if len(row) != len(header):
            raise ValueError(f"expected {len(header)} columns, found {len(row)}")
        data = dict(zip(header, (cell.strip() for cell in row)))

        timestamp = None
        if self._ts_column and data.get(self._ts_column):
            timestamp = _parse_timestamp(data[self._ts_column], self._ts_format)

        fields: dict[str, Any] = {}
        for column, value in data.items():
            semantic = self._columns.get(column)
            if semantic:
                fields[semantic] = value
            else:
                # Column present in real data but not in the mapping:
                # preserved under its raw name, reported as UNKNOWN.
                fields[f"UNKNOWN_{column}"] = value
        return ParsedLine(
            line_number=line_number,
            raw_text=raw_text,
            timestamp=timestamp,
            source=self.source_type,
            level=None,
            normalized={"msg": raw_text, "device": self.config.get("device"), "fields": fields},
        )

    def parse_file(self, ctx: FileContext, *, encoding: str = "utf-8") -> Any:
        """Establish the header first, then parse rows with it."""
        from app.parsers.base import ParseResult

        result = ParseResult(
            parser_code=self.code, parser_version=self.version, source_type=self.get_source_type()
        )
        with ctx.path.open("r", encoding=encoding, errors="replace", newline="") as fh:
            header: list[str] | None = None
            number = 0
            for raw in fh:
                number += 1
                line = raw.rstrip("\r\n")
                if not line.strip():
                    continue
                if header is None:
                    if not self._header_sig.search(line):
                        result.errors.append(f"line {number}: missing/invalid CSV header")
                        continue
                    header = next(csv.reader(io.StringIO(line), delimiter=self._delimiter))
                    self.config["_header"] = [h.strip() for h in header]
                    result.metadata["header"] = self.config["_header"]
                    continue
                try:
                    parsed = self.parse_line(line, number)
                except Exception as exc:
                    result.errors.append(f"line {number}: {type(exc).__name__}: {exc}")
                    continue
                if parsed is not None:
                    result.lines.append(parsed)
        self.config.pop("_header", None)
        result.metadata["encoding"] = encoding
        return result


def build_parser(code: str, source_type: str, config: dict[str, Any]) -> BaseParser:
    """Instantiate the right configured parser flavor from YAML data."""
    kind = config.get("type", "line")
    cls = ConfiguredCsvParser if kind == "csv" else ConfiguredLineParser
    parser = cls(code=code, source_type=source_type, config=config)
    parser.version = str(config.get("version", "1.0.0"))
    return parser
