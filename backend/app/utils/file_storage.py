"""Safe storage of uploaded / extracted files.

Layout below ``settings.storage_dir``::

    data/
      uploads/
        original/<yyyy>/<mm>/<file_id>__<safe-name>   # never modified
        extracted/<file_id>__<safe-name>              # per ZIP member

Rules:
* Original uploads are stored once and never mutated afterwards.
* Filenames are sanitized; storage names are prefixed with the file id,
  which guarantees uniqueness and removes any path-traversal risk.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import StorageError

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str, max_length: int = 120) -> str:
    """Return a filesystem-safe version of ``filename`` (no separators)."""
    name = unicodedata.normalize("NFKD", filename or "file")
    # Strip any directory components (path traversal defense-in-depth).
    name = name.replace("\\", "/").split("/")[-1]
    # Hidden extension-only names (".log") get a base so the type survives.
    if name.startswith(".") and name.count(".") == 1:
        name = "file" + name
    name = _SAFE_NAME_RE.sub("_", name).strip("._") or "file"
    root, dot, ext = name.rpartition(".")
    if len(name) > max_length:
        # Keep the extension intact.
        suffix = ("." + ext) if dot else ""
        name = name[: max_length - len(suffix)] + suffix
    return name


class FileStorage:
    """Manages the on-disk upload area."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or get_settings().storage_dir).resolve()

    # ---- paths -----------------------------------------------------------

    @property
    def upload_root(self) -> Path:
        return self.root / "uploads"

    @property
    def original_dir(self) -> Path:
        return self.upload_root / "original"

    @property
    def extracted_dir(self) -> Path:
        return self.upload_root / "extracted"

    def ensure_dirs(self) -> None:
        self.original_dir.mkdir(parents=True, exist_ok=True)
        self.extracted_dir.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: str) -> Path:
        """Resolve a stored relative path, refusing escapes from the root."""
        candidate = (self.root / relative_path).resolve()
        if not candidate.is_relative_to(self.root):
            raise StorageError(f"Stored path escapes storage root: {relative_path}")
        return candidate

    # ---- saving -----------------------------------------------------------

    def stored_name(self, file_id: str, original_filename: str) -> str:
        return f"{file_id}__{sanitize_filename(original_filename)}"

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    def save_stream(
        self,
        stream,
        *,
        file_id: str,
        original_filename: str,
        max_bytes: int | None = None,
    ) -> tuple[str, int, str]:
        """Persist an upload stream.

        Returns ``(relative_path, size_bytes, sha256)``.
        Raises :class:`FileTooLargeError` if ``max_bytes`` is exceeded.
        """
        self.ensure_dirs()
        now = datetime.now(timezone.utc)
        target_dir = self.original_dir / f"{now:%Y}" / f"{now:%m}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / self.stored_name(file_id, original_filename)

        size = 0
        digest = hashlib.sha256()
        try:
            with target.open("wb") as fh:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        fh.close()
                        target.unlink(missing_ok=True)
                        from app.core.errors import FileTooLargeError

                        raise FileTooLargeError(
                            f"Upload exceeds the maximum allowed size of "
                            f"{max_bytes // (1024 * 1024)} MB."
                        )
                    digest.update(chunk)
                    fh.write(chunk)
        except OSError as exc:
            from app.core.errors import StorageError

            raise StorageError(f"Could not write upload to storage: {exc}") from exc

        return self._relative(target), size, digest.hexdigest()

    def save_bytes(
        self, data: bytes, *, subdir: str, file_id: str, original_filename: str
    ) -> tuple[str, int, str]:
        """Persist an in-memory payload (used for extracted ZIP members)."""
        self.ensure_dirs()
        target_dir = (self.upload_root / subdir).resolve()
        if not target_dir.is_relative_to(self.upload_root):
            raise StorageError("Invalid extraction subdirectory.")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / self.stored_name(file_id, original_filename)
        try:
            target.write_bytes(data)
        except OSError as exc:
            raise StorageError(f"Could not write extracted file: {exc}") from exc

        return self._relative(target), len(data), hashlib.sha256(data).hexdigest()

    def delete(self, relative_path: str) -> None:
        try:
            self.resolve(relative_path).unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover
            raise StorageError(f"Could not delete stored file: {exc}") from exc


file_storage = FileStorage()
