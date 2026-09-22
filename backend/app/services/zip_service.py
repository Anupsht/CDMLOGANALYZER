"""Safe ZIP extraction.

Security measures (Phase 1 spec §6):

* reject absolute paths, ``..`` segments and drive letters (path traversal)
* enforce a maximum number of entries (file-count bombs)
* enforce a maximum **total uncompressed** size using the ZIP central
  directory metadata *before* writing (archive bombs)
* re-count bytes while copying (defense in depth against lying metadata)
* never write outside the ``uploads/extracted`` area — member names are
  only used as metadata; on disk everything is stored under a fresh id
* the original ZIP file is preserved untouched
"""

from __future__ import annotations

import hashlib
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.core.config import get_settings
from app.core.errors import ArchiveError
from app.utils.file_storage import FileStorage

logger = logging.getLogger(__name__)

# Chunk size while copying member data.
_COPY_CHUNK = 1024 * 1024


@dataclass
class ExtractedMember:
    original_path: str  # path inside the ZIP
    filename: str  # basename
    data: bytes  # content (extracted in memory; sizes are capped well below)
    size_bytes: int
    checksum_sha256: str


class SafeZipExtractor:
    def __init__(self, storage: FileStorage | None = None) -> None:
        self.storage = storage or FileStorage()

    # ---- validation --------------------------------------------------------

    def inspect(self, zip_path: Path) -> list[zipfile.ZipInfo]:
        """Open and validate the archive; return its safe member list."""
        if not zip_path.exists():
            raise ArchiveError("Archive file is missing on disk.")
        if not zipfile.is_zipfile(zip_path):
            raise ArchiveError("The uploaded file is not a valid ZIP archive.")

        settings = get_settings()
        try:
            with zipfile.ZipFile(zip_path) as zf:
                infos = [i for i in zf.infolist() if not i.is_dir()]
        except (zipfile.BadZipFile, OSError) as exc:
            raise ArchiveError(f"Archive could not be read: {exc}") from exc

        if len(infos) > settings.max_extract_files:
            raise ArchiveError(
                f"Archive contains {len(infos)} files; the maximum is "
                f"{settings.max_extract_files}."
            )

        blocked = settings.blocked_archive_extension_set
        ratio_limit = settings.max_zip_compression_ratio
        total = 0
        for info in infos:
            self._check_member_name(info.filename)
            # Phase 10: reject executable/active-content members outright.
            member_ext = PurePosixPath(info.filename.replace("\\", "/")).suffix.lower()
            if member_ext and member_ext in blocked:
                raise ArchiveError(
                    f"Archive contains a forbidden file type ({member_ext}): {info.filename!r}"
                )
            # Phase 10: per-member compression ratio (zip-bomb hardening on
            # top of the total extracted-size cap).
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > ratio_limit:
                    raise ArchiveError(
                        f"Archive member {info.filename!r} has a suspicious "
                        f"compression ratio ({ratio:.0f}:1); possible zip bomb."
                    )
            total += info.file_size
            if total > settings.max_extract_size_bytes:
                raise ArchiveError(
                    "Archive would extract to more than "
                    f"{settings.max_extract_size_bytes // (1024 * 1024)} MB "
                    "(possible archive bomb); rejected."
                )
        return infos

    @staticmethod
    def _check_member_name(name: str) -> None:
        """Reject dangerous member paths (path traversal etc.)."""
        path = PurePosixPath(name.replace("\\", "/"))
        if path.is_absolute() or name.startswith("/"):
            raise ArchiveError(f"Unsafe absolute path in archive: {name!r}")
        first = name.replace("\\", "/").split("/")[0]
        if len(first) <= 3 and ":" in first:
            # Windows drive letter like "C:" / "C:\evil.txt"
            raise ArchiveError(f"Unsafe drive path in archive: {name!r}")
        for part in path.parts:
            if part == "..":
                raise ArchiveError(f"Unsafe relative path in archive: {name!r}")

    # ---- extraction ----------------------------------------------------------

    def extract(self, zip_path: Path) -> list[ExtractedMember]:
        """Extract a validated archive, returning member descriptors."""
        infos = self.inspect(zip_path)
        members: list[ExtractedMember] = []

        settings = get_settings()
        extracted_total = 0
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for info in infos:
                    digest = hashlib.sha256()
                    chunks: list[bytes] = []
                    member_size = 0
                    with zf.open(info, "r") as member_fh:
                        while chunk := member_fh.read(_COPY_CHUNK):
                            member_size += len(chunk)
                            extracted_total += len(chunk)
                            if extracted_total > settings.max_extract_size_bytes:
                                raise ArchiveError(
                                    "Archive exceeded the allowed extracted size during "
                                    "extraction (possible archive bomb); aborted."
                                )
                            digest.update(chunk)
                            chunks.append(chunk)
                    data = b"".join(chunks)
                    members.append(
                        ExtractedMember(
                            original_path=info.filename,
                            filename=PurePosixPath(info.filename).name or info.filename,
                            data=data,
                            size_bytes=member_size,
                            checksum_sha256=digest.hexdigest(),
                        )
                    )
        except RuntimeError as exc:  # encrypted / unsupported compression
            raise ArchiveError(f"Archive member could not be extracted: {exc}") from exc
        except zipfile.BadZipFile as exc:
            raise ArchiveError(f"Archive is corrupted: {exc}") from exc

        logger.info(
            "ZIP extracted safely",
            extra={
                "operation": "zip.extract",
                "members": len(members),
                "bytes": extracted_total,
            },
        )
        return members


zip_extractor = SafeZipExtractor()
