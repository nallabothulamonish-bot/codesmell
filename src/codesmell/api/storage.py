"""Persistent upload storage with streaming size and integrity checks."""

from __future__ import annotations

import hashlib
import os
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from codesmell.config.settings import ApiSettings


class UploadRejected(ValueError):
    """Raised when an HTTP upload is not safe or supported."""


@dataclass(frozen=True, slots=True)
class StoredUpload:
    path: Path
    original_filename: str
    sha256: str
    size_bytes: int


class UploadStorage:
    def __init__(self, settings: ApiSettings) -> None:
        self._settings = settings
        self._root = settings.storage_root.resolve()
        self._uploads = self._root / "uploads"
        self._uploads.mkdir(parents=True, exist_ok=True)
        try:
            self._uploads.chmod(0o700)
        except OSError:
            pass

    @property
    def uploads_root(self) -> Path:
        return self._uploads

    async def save(self, upload: UploadFile) -> StoredUpload:
        original = Path(upload.filename or "upload").name
        suffix = Path(original).suffix.lower()
        if suffix not in self._settings.allowed_upload_suffixes:
            raise UploadRejected(
                f"unsupported upload suffix {suffix!r}; expected one of "
                f"{', '.join(self._settings.allowed_upload_suffixes)}"
            )

        destination = self._uploads / f"{uuid.uuid4().hex}{suffix}"
        digest = hashlib.sha256()
        total = 0
        try:
            with destination.open("xb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self._settings.max_upload_bytes:
                        raise UploadRejected(
                            f"upload exceeds {self._settings.max_upload_bytes} bytes"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

            if total == 0:
                raise UploadRejected("uploaded file is empty")
            if suffix == ".zip" and not zipfile.is_zipfile(destination):
                raise UploadRejected("uploaded .zip is not a valid ZIP archive")

            return StoredUpload(
                path=destination,
                original_filename=original,
                sha256=digest.hexdigest(),
                size_bytes=total,
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

    def delete(self, path: str | None) -> None:
        if not path:
            return
        candidate = Path(path).resolve()
        try:
            candidate.relative_to(self._uploads)
        except ValueError:
            return
        candidate.unlink(missing_ok=True)
