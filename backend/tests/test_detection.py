"""Log source detection framework tests."""

from __future__ import annotations

import pytest

from app.parsers.base import FileContext
from app.services.detection_service import (
    DetectionRule,
    SourceDetection,
    build_file_context,
    detection_service,
)


def _ctx(tmp_path, name, content: bytes = b"some content\n"):
    path = tmp_path / name
    path.write_bytes(content)
    return FileContext.from_path(path)


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("ecat.log", "ecat"),
        ("ECAT_2026.log", "ecat"),
        ("cim.log", "cim"),
        ("keeper.log", "keeper"),
        ("journal.jou", "jou"),
        ("noteinfo.txt", "noteinfo"),
        ("Note_Info.log", "noteinfo"),
    ],
)
def test_filename_detection(tmp_path, filename, expected):
    detection = detection_service.detect(_ctx(tmp_path, filename))
    assert detection.source_code == expected
    assert detection.method == "filename"


def test_content_signature_detection(tmp_path):
    ctx = _ctx(tmp_path, "upload_20260201.txt", b"header\nE-CAT service session\n")
    detection = detection_service.detect(ctx)
    assert detection.source_code == "ecat"
    assert detection.method == "content"


def test_extension_fallback(tmp_path):
    ctx = _ctx(tmp_path, "unknown-name-123.log", b"no known signature here")
    detection = detection_service.detect(ctx)
    assert detection.source_code == "application"
    assert detection.confidence < 0.5  # weak signal


def test_unknown_when_nothing_matches(tmp_path):
    ctx = FileContext.from_path(_ctx(tmp_path, "data.dat", b"\x00binary").path)
    ctx.extension = "dat"
    detection = detection_service.detect(ctx)
    assert detection.source_code == "unknown"


def test_zip_inner_path_hint(tmp_path):
    ctx = _ctx(tmp_path, "file1.log")
    ctx.hints["original_path"] = "logs/jou/journal.dat"
    detection = detection_service.detect(ctx)
    assert detection.source_code == "jou"


def test_framework_is_extensible(tmp_path):
    class CustomRule(DetectionRule):
        name = "custom"
        priority = 1  # evaluated first

        def detect(self, ctx) -> SourceDetection | None:
            if "MAGIC-XYZ" in ctx.head_text:
                return SourceDetection("application", 0.99, self.name, "MAGIC-XYZ")
            return None

    detection_service.register_rule(CustomRule())
    try:
        ctx = _ctx(tmp_path, "anything.txt", b"MAGIC-XYZ payload")
        detection = detection_service.detect(ctx)
        assert detection.source_code == "application"
        assert detection.method == "custom"
    finally:
        detection_service._rules = [r for r in detection_service._rules if r.name != "custom"]


def test_build_file_context_overrides_filename(tmp_path):
    path = tmp_path / "renamed.log"
    path.write_text("x\n")
    ctx = build_file_context(path, filename="ecat.log")
    assert ctx.filename == "ecat.log"
    assert ctx.extension == "log"
