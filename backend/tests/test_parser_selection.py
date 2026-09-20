"""Parser framework tests: registry, selection, generic parsing."""

from __future__ import annotations

import pytest

from app.parsers.base import FileContext
from app.parsers.generic_text_parser import GenericTextParser
from app.parsers.registry import (
    GENERIC_FALLBACK_CODE,
    ParserRegistry,
    load_builtin_parsers,
    parser_registry,
)


@pytest.fixture(autouse=True)
def _builtin_parsers():
    load_builtin_parsers()


def _ctx(tmp_path, name="app.log", content: bytes | None = None):
    path = tmp_path / name
    path.write_bytes(content or b"2026-01-05 08:00:01 INFO hello\n")
    return FileContext.from_path(path)


def test_generic_parser_registered():
    parser = parser_registry.get(GENERIC_FALLBACK_CODE)
    assert isinstance(parser, GenericTextParser)
    assert parser.get_source_type() == "unknown"


def test_registry_select_returns_generic_for_text(tmp_path):
    parser = parser_registry.select(_ctx(tmp_path))
    assert parser.code == GENERIC_FALLBACK_CODE


def test_registry_preferred_codes_win(tmp_path):
    class AlwaysParser(GenericTextParser):
        code = "always_test"
        priority = 1

        def can_parse(self, ctx):
            return True

    registry = ParserRegistry()
    registry.register(AlwaysParser)
    parser = registry.select(_ctx(tmp_path), preferred_codes=["always_test"])
    assert parser.code == "always_test"


def test_registry_rejects_duplicate_codes():
    registry = ParserRegistry()
    registry.register(GenericTextParser)
    # Same class again → idempotent.
    registry.register(GenericTextParser)

    # A *different* class claiming the same code → rejected.
    class Impostor(GenericTextParser):
        code = GENERIC_FALLBACK_CODE

    with pytest.raises(ValueError):
        registry.register(Impostor)


def test_registry_falls_back_when_nothing_can_parse(tmp_path):
    binary = _ctx(tmp_path, "blob.bin", b"\x00\x01\x02PK\x03\x04")
    parser = parser_registry.select(binary)
    assert parser.code == GENERIC_FALLBACK_CODE


def test_generic_parser_extracts_timestamp_and_level(tmp_path):
    parser = GenericTextParser()
    lines = [
        "2026-01-05 08:00:01 INFO eCAT started",
        "[2026-01-05T08:00:02] WARNING low notes",
        "2026/01/05 08:00:03.123 ERROR jam",
        "no timestamp here ERROR still parsed",
    ]
    path = tmp_path / "mixed.log"
    path.write_text("\n".join(lines) + "\n")
    result = parser.parse_file(FileContext.from_path(path))

    assert result.parser_code == "generic_text"
    assert len(result.lines) == 4
    assert result.errors == []

    first = result.lines[0]
    assert first.timestamp is not None
    assert (first.timestamp.year, first.timestamp.hour) == (2026, 8)
    assert first.level == "INFO"
    assert first.raw_text == lines[0]  # raw text preserved verbatim
    assert first.normalized["text"] == lines[0]

    assert result.lines[1].level == "WARNING"
    assert result.lines[2].timestamp is not None
    assert result.lines[2].level == "ERROR"
    assert result.lines[3].timestamp is None


def test_parse_line_normalizes_structure():
    parser = GenericTextParser()
    parsed = parser.parse_line("2026-01-05 08:00:01 DEBUG pump 1", 1)
    assert parsed is not None
    assert parsed.line_number == 1
    assert parsed.normalized == {"text": "2026-01-05 08:00:01 DEBUG pump 1"}


def test_parser_version_registered_in_db(db_session):
    from app.models.parser import ParserVersion

    row = (
        db_session.query(ParserVersion)
        .filter_by(code="generic_text", version="1.0.0")
        .one_or_none()
    )
    assert row is not None
    assert row.is_active is True
