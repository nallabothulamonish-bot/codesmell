"""Workspace sandbox and settings tests."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from codesmell.config.settings import IngestionSettings, Settings
from codesmell.core.errors import PathEscapeError, WorkspaceError
from codesmell.ingestion.sandbox import WorkspaceManager


def test_workspace_is_created_private(workspace_manager: WorkspaceManager):
    import sys
    workspace = workspace_manager.create("job-1")
    try:
        if sys.platform != "win32":
            mode = stat.S_IMODE(workspace.root.stat().st_mode)
            assert mode == 0o700, "uploaded source must not be world-readable"
    finally:
        workspace.close()


def test_session_removes_workspace_on_success(workspace_manager: WorkspaceManager):
    with workspace_manager.session("job-2") as workspace:
        (workspace.source_dir / "a.py").write_text("x = 1\n")
        root = workspace.root
        assert root.exists()
    assert not root.exists()


def test_session_removes_workspace_on_exception(
    workspace_manager: WorkspaceManager,
):
    captured: Path | None = None
    with (
        pytest.raises(RuntimeError),
        workspace_manager.session("job-3") as workspace,
    ):
            captured = workspace.root
            (workspace.source_dir / "a.py").write_text("x = 1\n")
            raise RuntimeError("analysis blew up")

    assert captured is not None
    assert not captured.exists(), "teardown must not depend on a clean exit"


def test_close_is_idempotent(workspace_manager: WorkspaceManager):
    workspace = workspace_manager.create("job-4")
    workspace.close()
    workspace.close()
    assert not workspace.root.exists()


def test_duplicate_job_id_is_refused(workspace_manager: WorkspaceManager):
    first = workspace_manager.create("dupe")
    try:
        with pytest.raises(WorkspaceError):
            workspace_manager.create("dupe")
    finally:
        first.close()


def test_resolve_within_accepts_nested_relative_path(workspace):
    resolved = workspace.resolve_within(workspace.source_dir, "pkg/mod.py")
    assert resolved.is_relative_to(workspace.source_dir.resolve())


def test_resolve_within_rejects_traversal(workspace):
    with pytest.raises(PathEscapeError):
        workspace.resolve_within(workspace.source_dir, "../../escape.py")


def test_resolve_within_rejects_absolute_path(workspace):
    with pytest.raises(PathEscapeError):
        workspace.resolve_within(workspace.source_dir, "/etc/passwd")


def test_resolve_within_follows_symlinks_before_checking(workspace, tmp_path):
    """A symlink planted inside the sandbox must not become an escape hatch."""
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace.source_dir / "sneaky"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks not supported: {exc}")

    with pytest.raises(PathEscapeError):
        workspace.resolve_within(workspace.source_dir, "sneaky/payload.py")


def test_resolve_within_rejects_base_outside_workspace(workspace, tmp_path):
    with pytest.raises(WorkspaceError):
        workspace.resolve_within(tmp_path, "anything.py")


def test_usage_bytes_counts_written_files(workspace):
    (workspace.source_dir / "a.py").write_text("x" * 100)
    (workspace.source_dir / "b.py").write_text("y" * 50)
    assert workspace.usage_bytes() == 150


# --------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------- #


def test_production_rejects_debug_mode(tmp_path):
    with pytest.raises(ValueError, match="debug must be off"):
        Settings(environment="production", debug=True, workspace_root=tmp_path)


def test_production_rejects_workspace_retention(tmp_path):
    with pytest.raises(ValueError, match="keep_workspaces"):
        Settings(
            environment="production", keep_workspaces=True, workspace_root=tmp_path
        )


def test_production_rejects_open_git_host_allowlist(tmp_path):
    with pytest.raises(ValueError, match="git_allow_any_host"):
        Settings(
            environment="production",
            workspace_root=tmp_path,
            ingestion=IngestionSettings(git_allow_any_host=True),
        )


def test_incoherent_size_limits_are_refused():
    with pytest.raises(ValueError, match="max_member_bytes"):
        IngestionSettings(max_member_bytes=2048, max_uncompressed_bytes=1024)


def test_unknown_log_level_is_refused():
    from codesmell.config.settings import LoggingSettings

    with pytest.raises(ValueError, match="log level"):
        LoggingSettings(level="CHATTY")


def test_log_level_is_normalised_to_upper_case():
    from codesmell.config.settings import LoggingSettings

    assert LoggingSettings(level="debug").level == "DEBUG"
