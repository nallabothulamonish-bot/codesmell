"""Project inventory construction.

Walks an ingested tree once and produces a :class:`ProjectInventory`. Symlinks
are never followed: a symlink inside an uploaded project could point at the host
filesystem, and following one would also make a cyclic tree walk forever.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath

from codesmell.config.logging import get_logger, safe_extra
from codesmell.config.settings import IngestionSettings
from codesmell.core.enums import Language, RejectionReason, SourceKind
from codesmell.core.errors import EmptyProjectError
from codesmell.core.models import ProjectInventory, Rejection, SourceFile
from codesmell.ingestion.detection import (
    BuildToolDetector,
    DependencyDetector,
    LanguageDetector,
)
from codesmell.ingestion.filters import (
    PathFilter,
    count_lines,
    looks_binary,
    read_source,
    sorted_rejections,
)

logger = get_logger(__name__)

#: Directory names that mark a source root rather than an archive wrapper.
_SOURCE_ROOT_NAMES: frozenset[str] = frozenset(
    {"src", "source", "sources", "lib", "app", "main", "python", "java"}
)


class ProjectInventoryBuilder:
    """Builds the structural census of a project directory."""

    def __init__(
        self,
        settings: IngestionSettings,
        path_filter: PathFilter | None = None,
        *,
        language_detector: LanguageDetector | None = None,
        build_tool_detector: BuildToolDetector | None = None,
        dependency_detector: DependencyDetector | None = None,
    ) -> None:
        self._settings = settings
        self._filter = path_filter or PathFilter(
            max_file_bytes=settings.max_source_file_bytes
        )
        self._languages = language_detector or LanguageDetector()
        self._build_tools = build_tool_detector or BuildToolDetector()
        self._dependencies = dependency_detector or DependencyDetector()

    def build(
        self,
        root: Path,
        *,
        name: str,
        source_kind: SourceKind,
        origin: str = "",
    ) -> ProjectInventory:
        """Scan ``root`` and return its inventory.

        Raises:
            EmptyProjectError: when nothing analysable survives filtering.
        """
        project_root = root.resolve()
        if not project_root.is_dir():
            raise EmptyProjectError(
                "project root is not a directory", path=str(project_root)
            )

        source_files, rejections = self._scan(project_root)

        if not source_files:
            raise EmptyProjectError(
                "no analysable source files were found after filtering",
                project=name,
                rejected=len(rejections),
                languages=sorted(Language.supported(), key=lambda lang: lang.value),
            )

        dependencies = self._dependencies.detect(project_root)
        inventory = ProjectInventory(
            name=name,
            source_kind=source_kind,
            primary_language=self._languages.primary(source_files),
            languages=self._languages.counts(source_files),
            build_tools=self._build_tools.detect(project_root),
            source_files=tuple(source_files),
            dependencies=dependencies,
            rejections=sorted_rejections(rejections),
            origin=origin,
        )

        logger.info("inventory built", extra=safe_extra(inventory.summary()))
        return inventory

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def resolve_root(root: Path) -> Path:
        """Resolve the true project root, unwrapping an archive wrapper.

        Public and called by the ingestion service *before* :meth:`build`, not
        inside it. Keeping the two separate is what guarantees that the root
        the service reports is the same root every ``relative_path`` is
        relative to -- when ``build`` descended internally, the caller was
        handed a root one level above the paths, and every later file read
        missed.


        ``repo-main.zip`` extracts to ``repo-main/<actual project>``. Without
        this, every ``relative_path`` in the inventory is prefixed with a
        meaningless segment that changes between downloads of the same repo --
        which would break the content fingerprint and the feature cache.

        GitHub adds exactly one level, so this descends at most one level. A
        greedy descent would walk straight past the real project root of a
        ``root/src/app/`` layout and strip meaningful path prefixes, which
        would in turn change every ``relative_path`` the metrics engine keys on.
        """
        try:
            entries = [e for e in root.iterdir() if not e.name.startswith(".")]
        except OSError:
            return root

        if len(entries) != 1 or not entries[0].is_dir():
            return root
        if entries[0].name.lower() in _SOURCE_ROOT_NAMES:
            # ``root/src/`` means root IS the project; ``src`` is not a wrapper.
            return root
        return entries[0]

    def _scan(self, root: Path) -> tuple[list[SourceFile], list[Rejection]]:
        source_files: list[SourceFile] = []
        rejections: list[Rejection] = []
        limit_reached = False

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            directory = Path(dirpath)

            # Prune in place so os.walk never descends into excluded trees.
            dirnames[:] = [
                d
                for d in sorted(dirnames)
                if not self._filter.should_skip_dir(d)
                and not PathFilter.is_virtualenv(directory / d)
                and not (directory / d).is_symlink()
            ]

            for filename in sorted(filenames):
                if limit_reached:
                    break

                path = directory / filename
                relative = _relative_posix(path, root)

                if path.is_symlink():
                    rejections.append(
                        Rejection(relative, RejectionReason.SYMLINK)
                    )
                    continue

                try:
                    stat_result = path.stat()
                except OSError:
                    rejections.append(
                        Rejection(
                            relative, RejectionReason.SPECIAL_FILE, "unreadable"
                        )
                    )
                    continue

                if not path.is_file():
                    rejections.append(
                        Rejection(relative, RejectionReason.SPECIAL_FILE)
                    )
                    continue

                verdict = self._filter.screen(relative, stat_result.st_size)
                if verdict is not None:
                    rejections.append(verdict)
                    continue

                if looks_binary(path):
                    rejections.append(
                        Rejection(relative, RejectionReason.BINARY_CONTENT)
                    )
                    continue

                text = read_source(path)
                if text is None:
                    rejections.append(
                        Rejection(relative, RejectionReason.UNDECODABLE)
                    )
                    continue

                source_files.append(
                    SourceFile(
                        relative_path=relative,
                        language=self._filter.language_of(relative),
                        size_bytes=stat_result.st_size,
                        line_count=count_lines(text),
                        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    )
                )

                if len(source_files) >= self._settings.max_source_files:
                    limit_reached = True
                    rejections.append(
                        Rejection(
                            relative,
                            RejectionReason.MEMBER_LIMIT,
                            f"stopped at {self._settings.max_source_files} files",
                        )
                    )

            if limit_reached:
                break

        return source_files, rejections


def _relative_posix(path: Path, root: Path) -> str:
    """POSIX-style path relative to ``root``, stable across platforms."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = Path(path.name)
    return PurePosixPath(*relative.parts).as_posix()
