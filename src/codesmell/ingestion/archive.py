"""Hardened archive extraction.

Uploaded archives are hostile input. Python's :meth:`zipfile.ZipFile.extractall`
is not safe for untrusted data, so this module never calls it. Every member is
inspected first, then streamed out through
:meth:`~codesmell.ingestion.sandbox.Workspace.resolve_within`.

Defended against:

* **zip-slip** -- members named ``../../etc/passwd`` or with absolute paths.
* **zip-bombs** -- via per-member size, total size and compression-ratio caps.
* **symlink escapes** -- symlink members are refused outright, so a later write
  cannot be redirected through one.
* **member floods** -- millions of tiny entries exhausting inodes.
* **declared-vs-actual size lies** -- the streaming loop enforces the cap on
  bytes actually written, not on the header's claim.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

from codesmell.config.logging import get_logger
from codesmell.config.settings import IngestionSettings
from codesmell.core.enums import RejectionReason
from codesmell.core.errors import (
    ArchiveTooLargeError,
    CorruptArchiveError,
    UnsafeArchiveMemberError,
)
from codesmell.core.models import ExtractionReport, Rejection
from codesmell.core.ports import ArchiveExtractor
from codesmell.ingestion.sandbox import Workspace

logger = get_logger(__name__)

_CHUNK_SIZE = 64 * 1024
_S_IFMT_MASK = 0o170000


class SafeZipExtractor(ArchiveExtractor):
    """A ZIP extractor that treats the archive as an attacker would write it."""

    def __init__(self, settings: IngestionSettings, workspace: Workspace) -> None:
        self._settings = settings
        self._workspace = workspace

    def supports(self, archive_path: Path) -> bool:
        return archive_path.suffix.lower() in self._settings.allowed_archive_suffixes

    def extract(self, archive_path: Path, destination: Path) -> ExtractionReport:
        self._check_archive_size(archive_path)
        destination.mkdir(parents=True, exist_ok=True)

        rejections: list[Rejection] = []
        files_written = 0
        bytes_written = 0

        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.infolist()
                self._check_member_count(len(members), archive_path)
                self._check_declared_totals(members, archive_path)

                for info in members:
                    verdict = self._screen(info)
                    if verdict is not None:
                        rejections.append(verdict)
                        continue

                    if info.is_dir():
                        self._workspace.resolve_within(
                            destination, info.filename
                        ).mkdir(parents=True, exist_ok=True)
                        continue

                    remaining = self._settings.max_uncompressed_bytes - bytes_written
                    written = self._write_member(
                        archive, info, destination, remaining
                    )
                    files_written += 1
                    bytes_written += written

        except zipfile.BadZipFile as exc:
            raise CorruptArchiveError(
                f"archive is not a readable ZIP file: {exc}",
                archive=archive_path.name,
            ) from exc

        logger.info(
            "archive extracted",
            extra={
                "archive": archive_path.name,
                "files_written": files_written,
                "bytes_written": bytes_written,
                "rejected": len(rejections),
            },
        )
        return ExtractionReport(
            files_written=files_written,
            bytes_written=bytes_written,
            rejections=tuple(rejections),
        )

    # ------------------------------------------------------------------ #
    # Pre-flight checks
    # ------------------------------------------------------------------ #

    def _check_archive_size(self, archive_path: Path) -> None:
        if not archive_path.is_file():
            raise CorruptArchiveError(
                "archive path is not a regular file", path=str(archive_path)
            )
        size = archive_path.stat().st_size
        if size == 0:
            raise CorruptArchiveError("archive is empty", path=archive_path.name)
        if size > self._settings.max_archive_bytes:
            raise ArchiveTooLargeError(
                "archive exceeds the maximum upload size",
                size_bytes=size,
                limit_bytes=self._settings.max_archive_bytes,
            )

    def _check_member_count(self, count: int, archive_path: Path) -> None:
        if count > self._settings.max_members:
            raise ArchiveTooLargeError(
                "archive contains too many members",
                members=count,
                limit=self._settings.max_members,
                archive=archive_path.name,
            )

    def _check_declared_totals(
        self, members: list[zipfile.ZipInfo], archive_path: Path
    ) -> None:
        """Reject obvious bombs before writing a single byte."""
        declared_uncompressed = sum(m.file_size for m in members)
        if declared_uncompressed > self._settings.max_uncompressed_bytes:
            raise ArchiveTooLargeError(
                "archive declares more uncompressed data than permitted",
                declared_bytes=declared_uncompressed,
                limit_bytes=self._settings.max_uncompressed_bytes,
                archive=archive_path.name,
            )

        declared_compressed = sum(m.compress_size for m in members)
        if declared_compressed > 0:
            ratio = declared_uncompressed / declared_compressed
            if ratio > self._settings.max_compression_ratio:
                raise ArchiveTooLargeError(
                    "archive compression ratio indicates a zip bomb",
                    ratio=round(ratio, 2),
                    limit=self._settings.max_compression_ratio,
                    archive=archive_path.name,
                )

    # ------------------------------------------------------------------ #
    # Per-member screening
    # ------------------------------------------------------------------ #

    def _screen(self, info: zipfile.ZipInfo) -> Rejection | None:
        """Return a :class:`Rejection` if the member must not be extracted."""
        name = info.filename

        if not name or name in (".", "./"):
            return Rejection(name, RejectionReason.SPECIAL_FILE, "empty member name")

        # ZIP stores POSIX separators; a backslash here is a Windows-targeted
        # traversal attempt that PurePosixPath would treat as a filename.
        normalised = name.replace("\\", "/")

        if normalised.startswith("/") or _has_drive_letter(normalised):
            return Rejection(name, RejectionReason.ABSOLUTE_PATH)

        if any(part == ".." for part in normalised.split("/")):
            return Rejection(name, RejectionReason.PATH_TRAVERSAL)

        # Windows-created archives and zipfile.writestr() record permission
        # bits with no file-type bits at all, so a zero format field means
        # "unspecified", not "special file". Only an explicitly non-regular
        # type is grounds for rejection.
        file_type = (info.external_attr >> 16) & _S_IFMT_MASK
        if file_type == stat.S_IFLNK:
            return Rejection(name, RejectionReason.SYMLINK)
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            return Rejection(
                name,
                RejectionReason.SPECIAL_FILE,
                f"file type {oct(file_type)}",
            )

        if not info.is_dir() and info.file_size > self._settings.max_member_bytes:
            return Rejection(
                name,
                RejectionReason.MEMBER_TOO_LARGE,
                f"{info.file_size} > {self._settings.max_member_bytes}",
            )

        if not info.is_dir() and info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > self._settings.max_compression_ratio:
                return Rejection(
                    name,
                    RejectionReason.COMPRESSION_RATIO,
                    f"ratio {ratio:.1f}",
                )

        return None

    # ------------------------------------------------------------------ #
    # Extraction
    # ------------------------------------------------------------------ #

    def _write_member(
        self,
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        destination: Path,
        remaining_budget: int,
    ) -> int:
        """Stream one member out, enforcing the budget on real bytes written."""
        safe_name = info.filename.replace("\\", "/")
        target = self._workspace.resolve_within(destination, safe_name)
        target.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        try:
            with archive.open(info) as src, target.open("wb") as dst:
                while chunk := src.read(_CHUNK_SIZE):
                    written += len(chunk)
                    if written > self._settings.max_member_bytes:
                        raise UnsafeArchiveMemberError(
                            "member expands beyond the per-file limit",
                            member=info.filename,
                            limit_bytes=self._settings.max_member_bytes,
                        )
                    if written > remaining_budget:
                        raise ArchiveTooLargeError(
                            "archive expands beyond the total size limit",
                            member=info.filename,
                            limit_bytes=self._settings.max_uncompressed_bytes,
                        )
                    dst.write(chunk)
        except (UnsafeArchiveMemberError, ArchiveTooLargeError):
            target.unlink(missing_ok=True)
            raise
        except (OSError, zipfile.BadZipFile) as exc:
            target.unlink(missing_ok=True)
            raise CorruptArchiveError(
                f"failed to extract member: {exc}", member=info.filename
            ) from exc

        return written


def _has_drive_letter(name: str) -> bool:
    """Detect ``C:/...`` style absolute Windows paths."""
    return len(name) >= 2 and name[1] == ":" and name[0].isalpha()
