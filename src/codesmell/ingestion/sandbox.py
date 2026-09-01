"""Sandboxed workspaces.

Every ingestion gets an isolated directory that is destroyed when the job ends,
success or failure. Nothing from an uploaded project is ever executed or
imported -- files are only read as text and parsed.

:func:`Workspace.resolve_within` is the single containment primitive used by the
archive extractor and the inventory scanner. Both go through it, so path-escape
protection is enforced in exactly one place.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from codesmell.config.logging import get_logger
from codesmell.core.errors import PathEscapeError, WorkspaceError

logger = get_logger(__name__)


class Workspace:
    """An isolated directory tree for one ingestion job."""

    __slots__ = ("_closed", "_job_id", "_root")

    def __init__(self, root: Path, job_id: str) -> None:
        self._root = root.resolve()
        self._job_id = job_id
        self._closed = False

    @property
    def root(self) -> Path:
        return self._root

    @property
    def job_id(self) -> str:
        return self._job_id

    @property
    def source_dir(self) -> Path:
        """Where project source is unpacked or cloned."""
        return self._subdir("source")

    @property
    def upload_dir(self) -> Path:
        """Where the raw upload is staged before extraction."""
        return self._subdir("upload")

    def _subdir(self, name: str) -> Path:
        path = self._root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve_within(self, base: Path, candidate: str | Path) -> Path:
        """Resolve ``candidate`` against ``base`` and prove it stays inside.

        This defeats zip-slip (``../../etc/passwd``), absolute-path members and
        symlink-assisted escapes in one check, because it compares the *fully
        resolved* paths -- symlinks included -- rather than the textual ones.

        Raises:
            PathEscapeError: if the resolved path is outside ``base``.
        """
        base_resolved = base.resolve()
        if not self._is_within(base_resolved, self._root):
            raise WorkspaceError(
                "base directory is outside this workspace",
                base=str(base_resolved),
                workspace=str(self._root),
            )

        target = (base_resolved / candidate).resolve()
        if not self._is_within(target, base_resolved):
            raise PathEscapeError(
                "resolved path escapes its base directory",
                candidate=str(candidate),
                resolved=str(target),
                base=str(base_resolved),
            )
        return target

    @staticmethod
    def _is_within(target: Path, base: Path) -> bool:
        try:
            target.relative_to(base)
        except ValueError:
            return False
        return True

    def usage_bytes(self) -> int:
        """Total size of files currently in the workspace."""
        total = 0
        for dirpath, _dirnames, filenames in os.walk(self._root):
            for filename in filenames:
                path = Path(dirpath) / filename
                if path.is_symlink() or not path.is_file():
                    continue
                total += path.stat().st_size
        return total

    def close(self) -> None:
        """Delete the workspace. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        shutil.rmtree(self._root, ignore_errors=True)
        logger.debug("workspace removed", extra={"workspace": str(self._root)})

    def __repr__(self) -> str:
        return f"Workspace(root={str(self._root)!r}, job_id={self._job_id!r})"


class WorkspaceManager:
    """Creates and disposes of workspaces under a configured root."""

    def __init__(self, workspace_root: Path, *, keep: bool = False) -> None:
        self._workspace_root = Path(workspace_root)
        self._keep = keep

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def create(self, job_id: str | None = None, *, overwrite: bool = False) -> Workspace:
        job = job_id or uuid.uuid4().hex
        root = self._workspace_root / job
        if root.exists():
            if not overwrite:
                raise WorkspaceError(
                    "workspace already exists", job_id=job, path=str(root)
                )
            shutil.rmtree(root, ignore_errors=True)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceError(
                f"cannot create workspace: {exc}", path=str(root)
            ) from exc

        # 0o700: nothing else on the host may read a user's uploaded source.
        root.chmod(0o700)
        logger.debug("workspace created", extra={"workspace": str(root)})
        return Workspace(root, job)

    @contextmanager
    def session(self, job_id: str | None = None) -> Iterator[Workspace]:
        """Yield a workspace and tear it down unconditionally afterwards."""
        workspace = self.create(job_id, overwrite=True)
        try:
            yield workspace
        finally:
            if self._keep:
                logger.warning(
                    "workspace retained (keep_workspaces enabled)",
                    extra={"workspace": str(workspace.root)},
                )
            else:
                workspace.close()
