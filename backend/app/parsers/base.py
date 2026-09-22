"""Parser interface.

A parser answers four questions (per the Phase 1 interface contract):

* ``can_parse(ctx)``     — can this parser handle the given file?
* ``parse_file(ctx)``    — parse the whole file into a ParseResult
* ``parse_line(raw, n)`` — parse a single line into a ParsedLine
* ``get_source_type()``  — which log source this parser targets
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Iterator


@dataclass
class FileContext:
    """Everything a parser/adapter may need to inspect a candidate file.

    Built by the pipeline before identification; ``head_text`` contains
    the first N KB decoded (lossy) so rules never need to re-read disk.
    """

    path: Path
    filename: str
    extension: str
    size_bytes: int
    head_text: str = ""
    head_bytes: bytes = b""
    # Hints gathered earlier in the pipeline (ZIP inner path, upload form data…)
    hints: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_path(cls, path: str | Path, *, read_head: int = 64 * 1024, hints: dict | None = None) -> "FileContext":
        p = Path(path)
        head = b""
        try:
            with p.open("rb") as fh:
                head = fh.read(read_head)
        except OSError:
            head = b""
        head_text = head.decode("utf-8", errors="replace")
        return cls(
            path=p,
            filename=p.name,
            extension=p.suffix.lower().lstrip("."),
            size_bytes=p.stat().st_size if p.exists() else 0,
            head_text=head_text,
            head_bytes=head,
            hints=hints or {},
        )


@dataclass
class ParsedLine:
    """Normalized preliminary structure for a single raw line."""

    line_number: int
    raw_text: str
    timestamp: datetime | None = None
    source: str | None = None
    level: str | None = None
    normalized: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    parser_code: str
    parser_version: str
    source_type: str
    lines: list[ParsedLine] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseParser(ABC):
    """Contract every log parser must fulfill.

    Subclasses declare ``code`` / ``version`` / ``source_type`` and are
    registered with :mod:`app.parsers.registry`. Real model parsers
    (P2600N, P2800N) will subclass this in Phase 2.
    """

    code: ClassVar[str] = "base"
    version: ClassVar[str] = "0.0.0"
    source_type: ClassVar[str] = "unknown"
    description: ClassVar[str] = ""
    # Lower priority number = tried earlier during selection.
    priority: ClassVar[int] = 100

    # ---- capability ------------------------------------------------------

    @abstractmethod
    def can_parse(self, ctx: FileContext) -> bool:
        """Return True if this parser can handle the described file."""

    @abstractmethod
    def parse_line(self, raw_text: str, line_number: int) -> ParsedLine | None:
        """Parse one raw line. Return None to skip the line entirely."""

    def parse_file(self, ctx: FileContext, *, encoding: str = "utf-8") -> ParseResult:
        """Default implementation: stream the file line by line."""
        result = ParseResult(
            parser_code=self.code,
            parser_version=self.version,
            source_type=self.get_source_type(),
        )
        for number, raw in self._iter_lines(ctx.path, encoding=encoding):
            try:
                parsed = self.parse_line(raw, number)
            except Exception as exc:  # one bad line must not kill the file
                result.errors.append(f"line {number}: {type(exc).__name__}: {exc}")
                continue
            if parsed is not None:
                result.lines.append(parsed)
        result.metadata["encoding"] = encoding
        return result

    def get_source_type(self) -> str:
        return self.source_type

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _iter_lines(path: Path, encoding: str = "utf-8") -> Iterator[tuple[int, str]]:
        with path.open("r", encoding=encoding, errors="replace", newline="") as fh:
            number = 0
            for raw in fh:
                number += 1
                # Normalize newlines but keep the original characters otherwise.
                yield number, raw.rstrip("\r\n")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} {self.code}@{self.version}>"
