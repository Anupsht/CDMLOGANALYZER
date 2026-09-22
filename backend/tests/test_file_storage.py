"""Filename sanitization / storage safety tests."""

from __future__ import annotations

import pytest

from app.core.errors import StorageError
from app.utils.file_storage import FileStorage, sanitize_filename


def test_sanitize_removes_path_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\win.ini") == "win.ini"
    assert sanitize_filename("/abs/path/file.log") == "file.log"


def test_sanitize_handles_weird_names():
    assert sanitize_filename("") == "file"
    assert sanitize_filename("....") == "file"
    assert sanitize_filename(".log") == "file.log"
    assert sanitize_filename("my log (1).txt") == "my_log_1_.txt"
    # Long names keep their extension
    long = "a" * 300 + ".log"
    sanitized = sanitize_filename(long)
    assert len(sanitized) <= 120
    assert sanitized.endswith(".log")


def test_stored_name_prefixes_file_id():
    storage = FileStorage()
    name = storage.stored_name("abc123", "../../evil.txt")
    assert name.startswith("abc123__")
    assert name.endswith("evil.txt")
    assert "/" not in name and ".." not in name


def test_resolve_rejects_escape(tmp_path):
    storage = FileStorage(root=tmp_path)
    with pytest.raises(StorageError):
        storage.resolve("../outside.txt")
