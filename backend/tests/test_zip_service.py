"""Safe ZIP extraction tests: extraction, traversal rejection, bombs."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.core.errors import ArchiveError
from app.services.zip_service import zip_extractor


def _make_zip(path, entries: dict[str, bytes]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def test_extract_records_members_with_checksums(tmp_path):
    zip_path = _make_zip(
        tmp_path / "logs.zip",
        {
            "logs/ecat.log": b"line one\nline two\n",
            "logs/sub/keeper.txt": b"keeper data",
        },
    )
    members = zip_extractor.extract(zip_path)

    by_name = {m.original_path: m for m in members}
    assert set(by_name) == {"logs/ecat.log", "logs/sub/keeper.txt"}
    ecat = by_name["logs/ecat.log"]
    assert ecat.filename == "ecat.log"
    assert ecat.size_bytes == len(b"line one\nline two\n")
    import hashlib

    assert ecat.checksum_sha256 == hashlib.sha256(b"line one\nline two\n").hexdigest()


def test_original_zip_is_preserved(tmp_path):
    zip_path = _make_zip(tmp_path / "logs.zip", {"a.log": b"aaa"})
    before = zip_path.read_bytes()
    zip_extractor.extract(zip_path)
    assert zip_path.read_bytes() == before  # never modified


def test_rejects_path_traversal(tmp_path):
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo("../evil.txt")
        zf.writestr(info, b"malicious")
    with pytest.raises(ArchiveError, match="[Uu]nsafe"):
        zip_extractor.extract(zip_path)


def test_rejects_absolute_and_drive_paths(tmp_path):
    absolute = tmp_path / "abs.zip"
    with zipfile.ZipFile(absolute, "w") as zf:
        zf.writestr(zipfile.ZipInfo("/etc/evil.txt"), b"x")
    with pytest.raises(ArchiveError):
        zip_extractor.extract(absolute)

    drive = tmp_path / "drive.zip"
    with zipfile.ZipFile(drive, "w") as zf:
        zf.writestr(zipfile.ZipInfo("C:/evil.txt"), b"x")
    with pytest.raises(ArchiveError):
        zip_extractor.extract(drive)


def test_rejects_deep_traversal(tmp_path):
    deep = tmp_path / "deep.zip"
    with zipfile.ZipFile(deep, "w") as zf:
        zf.writestr(zipfile.ZipInfo("logs/../../out.txt"), b"x")
    with pytest.raises(ArchiveError, match="[Uu]nsafe"):
        zip_extractor.extract(deep)


def test_rejects_archive_bomb(tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_extract_size_mb", 0)  # 0-byte budget
    zip_path = _make_zip(tmp_path / "bomb.zip", {"big.log": b"x" * 1000})
    with pytest.raises(ArchiveError, match="bomb|extract"):
        zip_extractor.extract(zip_path)


def test_rejects_too_many_files(tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_extract_files", 2)
    zip_path = _make_zip(
        tmp_path / "many.zip",
        {"a.log": b"a", "b.log": b"b", "c.log": b"c"},
    )
    with pytest.raises(ArchiveError, match="maximum"):
        zip_extractor.extract(zip_path)


def test_rejects_non_zip(tmp_path):
    fake = tmp_path / "not.zip"
    fake.write_bytes(b"this is not a zip file")
    with pytest.raises(ArchiveError, match="not a valid ZIP"):
        zip_extractor.extract(fake)


def test_inline_upload_zip_end_to_end(client, tmp_path):
    """A ZIP upload through the API extracts children and parses logs."""
    # Lines use the P2600N eCAT format (config/models/p2600n/log_sources.yaml).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "P2600N/ecat.log",
            b"2026-02-01 10:00:00.000 [eCAT] INFO eCAT boot ok\n"
            b"2026-02-01 10:00:05.000 [eCAT] INFO keeper ready\n",
        )
        zf.writestr("P2600N/readme.txt", b"notes for the service engineer\n")
    buf.seek(0)

    resp = client.post(
        "/api/logs/upload",
        files={"file": ("fleet-logs.zip", buf, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] in {"COMPLETED", "PARTIAL"}

    detail = client.get(f"/api/logs/{body['id']}").json()
    children = client.get("/api/logs", params={"file_role": "extracted"}).json()["items"]
    assert len(children) == 2
    # Provenance is recorded for every extracted file.
    for child in children:
        assert child["parent_file_id"] == body["id"]
        assert child["original_path"]
        assert child["file_role"] == "extracted"

    # Source detection worked on inner files.
    sources = {c["log_source"]["code"] for c in children if c.get("log_source")}
    assert "ecat" in sources

    # Raw lines stored for parsed children.
    ecat_child = next(c for c in children if c["log_source"]["code"] == "ecat")
    lines = client.get(f"/api/logs/{ecat_child['id']}/lines").json()
    assert lines["total"] == 2
    assert lines["items"][0]["raw_text"] == "2026-02-01 10:00:00.000 [eCAT] INFO eCAT boot ok"
    assert lines["items"][0]["timestamp"] is not None
    _ = detail
