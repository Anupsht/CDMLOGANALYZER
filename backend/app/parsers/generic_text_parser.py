"""Generic text parser — the Phase 1 fallback.

Extracts what can be detected without model knowledge:
* timestamps in a few common formats
* log levels
* the raw text itself (always preserved verbatim for evidence tracing)

It produces a *normalized preliminary structure*; real interpretation
happens with model-specific parsers in Phase 2.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.parsers.base import BaseParser, FileContext, ParsedLine

# Timestamp patterns tried in order. Capture group 1 = the timestamp text.
_TIMESTAMP_PATTERNS = [
    # 2024-05-01T12:33:05, 2024-05-01 12:33:05.123, 2024/05/01 12:33:05
    re.compile(
        r"(\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?)"
    ),
    # [2024-05-01 12:33:05]  or (2024-05-01 12:33:05)
    re.compile(r"[\[(](\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?)[\])]"),
    # 01-05-2024 12:33:05
    re.compile(r"(\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2})"),
    # May  1 12:33:05 (syslog — year missing, not parsed)
]

_LEVEL_RE = re.compile(r"\b(TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|ERR|CRITICAL|FATAL)\b", re.IGNORECASE)

_LEVEL_ALIASES = {"WARN": "WARNING", "ERR": "ERROR"}


class GenericTextParser(BaseParser):
    code = "generic_text"
    version = "1.0.0"
    source_type = "unknown"
    description = "Generic line-oriented text parser (fallback for all models)."
    priority = 900

    TEXT_EXTENSIONS = {"txt", "log", "csv", "json", ""}

    def can_parse(self, ctx: FileContext) -> bool:
        # Accept anything that looks like decodable text.
        if ctx.extension and ctx.extension not in self.TEXT_EXTENSIONS:
            return False
        if not ctx.head_bytes:
            return False
        try:
            ctx.head_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return False
        # Cheap binary sniff: NUL bytes or an executable/zip magic.
        if b"\x00" in ctx.head_bytes[:4096]:
            return False
        return True

    def parse_line(self, raw_text: str, line_number: int) -> ParsedLine | None:
        normalized: dict = {"text": raw_text.strip()}
        timestamp = self.extract_timestamp(raw_text)
        level = self.extract_level(raw_text)
        return ParsedLine(
            line_number=line_number,
            raw_text=raw_text,
            timestamp=timestamp,
            source=self.source_type,
            level=level,
            normalized=normalized,
        )

    # ---- helpers (shared with Phase 2 parsers) ----------------------------

    @staticmethod
    def extract_timestamp(raw_text: str) -> datetime | None:
        for pattern in _TIMESTAMP_PATTERNS:
            match = pattern.search(raw_text)
            if not match:
                continue
            value = match.group(1).replace("/", "-").replace(",", ".")
            value = value.rstrip("Z")
            for fmt in (
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%d-%m-%Y %H:%M:%S",
            ):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None

    @staticmethod
    def extract_level(raw_text: str) -> str | None:
        match = _LEVEL_RE.search(raw_text)
        if not match:
            return None
        level = match.group(1).upper()
        return _LEVEL_ALIASES.get(level, level)
