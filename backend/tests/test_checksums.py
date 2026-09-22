"""Checksum utility tests."""

from __future__ import annotations

import hashlib

from app.utils.checksums import sha256_bytes, sha256_file


def test_known_vector():
    assert sha256_bytes(b"hello") == hashlib.sha256(b"hello").hexdigest()
    assert sha256_bytes(b"hello") == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_file_checksum_matches_bytes(tmp_path):
    data = b"x" * (3 * 1024 * 1024 + 17)  # multiple chunks + remainder
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    assert sha256_file(path) == sha256_bytes(data)


def test_file_checksum_of_real_log(tmp_path):
    content = b"2026-01-05 08:00:01 INFO eCAT application started\n"
    path = tmp_path / "app.log"
    path.write_bytes(content)
    assert sha256_file(path) == hashlib.sha256(content).hexdigest()
