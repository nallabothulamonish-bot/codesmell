"""Ingestion orchestration.

One entry point for all four intake paths (directory, archive, single file,
git URL). Everything downstream -- the parser, the metrics engine, the API --
receives a :class:`ProjectInventory` and does not care where it came from.

The caller owns the workspace lifetime::

    manager = WorkspaceManager(settings.workspace_root)
    with manager.session() as workspace:
        service = IngestionService(settings.ingestion, workspace)
        result = service.ingest_archive(uploaded_zip)
        ...  # analysis happens here, inside the workspace's lifetime
    # workspace and everything in it is now gone
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from codesmell.config.logging import get_logger
from codesmell.config.settings import IngestionSettings
from codesmell.core.enums import SourceKind
from codesmell.core.errors import (
    EmptyProjectError,
    UnsupportedSourceError,
)
from codesmell.core.models import IngestionResult, ProjectInventory
from codesmell.ingestion.archive import SafeZipExtractor
from codesmell.ingestion.filters import PathFilter
from codesmell.ingestion.git import GitRepositoryFetcher
from codesmell.ingestion.inventory import ProjectInventoryBuilder
from codesmell.ingestion.sandbox import Workspace

logger = get_logger(__name__)

_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class IngestionService:
    """Turns any supported source into a :class:`ProjectInventory`."""

    def __init__(
        self,
        settings: IngestionSettings,
        workspace: Workspace,
        *,
        path_filter: PathFilter | None = None,
        extractor: SafeZipExtractor | None = None,
        fetcher: GitRepositoryFetcher | None = None,
        inventory_builder: ProjectInventoryBuilder | None = None,
    ) -> None:
        self._settings = settings
        self._workspace = workspace
        self._extractor = extractor or SafeZipExtractor(settings, workspace)
        self._fetcher = fetcher or GitRepositoryFetcher(settings)
        self._inventory = inventory_builder or ProjectInventoryBuilder(
            settings, path_filter
        )

    # ------------------------------------------------------------------ #
    # Public intake paths
    # ------------------------------------------------------------------ #

    def ingest(
        self,
        source: str | Path,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> IngestionResult:
        """Dispatch on the shape of ``source``.

        A string that parses as a valid repository URL is cloned; otherwise the
        value is treated as a filesystem path.
        """
        if isinstance(source, str) and self._fetcher.supports(source):
            return self.ingest_repository(source, progress_callback=progress_callback)

        path = Path(source)
        if path.is_dir():
            return self.ingest_directory(path)
        if path.is_file():
            if self._extractor.supports(path):
                return self.ingest_archive(path)
            return self.ingest_single_file(path)

        raise UnsupportedSourceError(
            "source is neither an existing path nor an accepted repository URL",
            source=str(source)[:200],
        )

    def ingest_directory(self, directory: Path) -> IngestionResult:
        """Analyse a directory in place, without copying it."""
        directory = Path(directory).resolve()
        if not directory.is_dir():
            raise UnsupportedSourceError(
                "not a directory", path=str(directory)
            )

        project_root = self._inventory.resolve_root(directory)
        inventory = self._inventory.build(
            project_root,
            name=_safe_name(directory.name),
            source_kind=SourceKind.DIRECTORY,
            origin=str(directory),
        )
        return self._finish(inventory, project_root)

    def ingest_archive(self, archive_path: Path) -> IngestionResult:
        """Unpack an uploaded archive into the sandbox, then inventory it."""
        archive_path = Path(archive_path)
        if not self._extractor.supports(archive_path):
            raise UnsupportedSourceError(
                "unsupported archive format",
                suffix=archive_path.suffix,
                supported=list(self._settings.allowed_archive_suffixes),
            )

        destination = self._workspace.source_dir
        report = self._extractor.extract(archive_path, destination)

        if report.files_written == 0:
            raise EmptyProjectError(
                "archive contained no extractable files",
                archive=archive_path.name,
                rejected=len(report.rejections),
            )

        project_root = self._inventory.resolve_root(destination)
        inventory = self._inventory.build(
            project_root,
            name=_safe_name(archive_path.stem),
            source_kind=SourceKind.ARCHIVE,
            origin=archive_path.name,
        )
        warnings = (
            [f"{len(report.rejections)} archive member(s) were refused"]
            if report.rejections
            else []
        )
        return self._finish(inventory, project_root, warnings)

    def ingest_single_file(self, file_path: Path) -> IngestionResult:
        """Analyse one source file by staging it in the sandbox."""
        file_path = Path(file_path).resolve()
        if not file_path.is_file():
            raise UnsupportedSourceError("not a file", path=str(file_path))

        destination = self._workspace.source_dir
        staged = self._workspace.resolve_within(destination, file_path.name)
        shutil.copyfile(file_path, staged)

        inventory = self._inventory.build(
            destination,
            name=_safe_name(file_path.stem),
            source_kind=SourceKind.SINGLE_FILE,
            origin=file_path.name,
        )
        return self._finish(inventory, destination)

    def ingest_repository(
        self,
        url: str,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> IngestionResult:
        """Clone a public HTTPS repository, then inventory the working tree."""
        destination = self._workspace.source_dir / "repo"
        report = self._fetcher.fetch(url, destination, progress_callback=progress_callback)

        project_root = self._inventory.resolve_root(destination)
        inventory = self._inventory.build(
            project_root,
            name=_safe_name(self._fetcher.repository_name(url)),
            source_kind=SourceKind.GIT,
            origin=f"{report.url}@{report.revision[:12]}",
        )
        return self._finish(inventory, project_root)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _finish(
        self,
        inventory: ProjectInventory,
        root: Path,
        warnings: list[str] | None = None,
    ) -> IngestionResult:
        collected = list(warnings or [])
        collected.extend(self._quality_warnings(inventory))
        return IngestionResult(
            inventory=inventory, root=root, warnings=tuple(collected)
        )

    @staticmethod
    def _quality_warnings(inventory: ProjectInventory) -> list[str]:
        """Flag conditions that would quietly weaken downstream results."""
        warnings: list[str] = []

        if not inventory.primary_language.is_supported:
            warnings.append(
                f"primary language {inventory.primary_language.value!r} has no "
                "parser adapter; results will be partial"
            )
        if inventory.file_count < 5:
            warnings.append(
                f"only {inventory.file_count} source file(s) found; "
                "project-relative feature scaling will be unreliable"
            )
        if inventory.total_lines < 200:
            warnings.append(
                "project is very small; cross-project metrics are unlikely "
                "to be meaningful"
            )
        return warnings


def _safe_name(raw: str) -> str:
    """Normalise a project name for use in paths, logs and report filenames."""
    cleaned = _UNSAFE_NAME_RE.sub("-", raw).strip("-.")
    return cleaned[:80] or "project"
