"""CLI behaviour and the git clone path.

The clone tests use a stub ``git`` executable rather than the network, so they
exercise the real :mod:`subprocess` code path -- argv construction, environment
hardening, timeout and failure handling -- deterministically and offline.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codesmell.cli import app
from codesmell.config.settings import IngestionSettings
from codesmell.core.errors import RepositoryFetchError, RepositoryTimeoutError
from codesmell.ingestion.git import GitRepositoryFetcher, _sanitise

runner = CliRunner()


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "codesmell" in result.stdout


def test_config_command_reports_wiring(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    from codesmell.config.settings import get_settings

    get_settings.cache_clear()

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0
    assert "python" in result.stdout
    get_settings.cache_clear()


def test_ingest_command_prints_inventory(sample_project, tmp_path, monkeypatch):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    from codesmell.config.settings import get_settings

    get_settings.cache_clear()

    result = runner.invoke(app, ["ingest", str(sample_project)])

    assert result.exit_code == 0
    assert "service.py" in result.stdout
    assert "python" in result.stdout
    get_settings.cache_clear()


def test_ingest_command_json_output(sample_project, tmp_path, monkeypatch):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    from codesmell.config.settings import get_settings

    get_settings.cache_clear()

    result = runner.invoke(app, ["ingest", str(sample_project), "--json"])

    assert result.exit_code == 0
    assert "fingerprint" in result.stdout
    get_settings.cache_clear()


def test_ingest_command_exits_nonzero_on_bad_source(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    from codesmell.config.settings import get_settings

    get_settings.cache_clear()

    result = runner.invoke(app, ["ingest", "/no/such/path"])

    assert result.exit_code == 1
    assert "unsupported_source" in result.stdout
    get_settings.cache_clear()


# --------------------------------------------------------------------- #
# Git clone
# --------------------------------------------------------------------- #


def _stub_git(tmp_path: Path, body: str, name: str = "git") -> Path:
    """Write an executable stub standing in for ``git``."""
    import sys
    py_code = f"""import sys, os, time, pathlib
args = sys.argv[1:]
body_text = {repr(body)}

if "exit 128" in body_text:
    sys.stderr.write("fatal: repository not found\\n")
    sys.exit(128)

if "sleep 30" in body_text:
    time.sleep(30)
    sys.exit(0)

if args and args[0] == "rev-parse":
    if "exit 1;" in body_text and "$1" in body_text:
        sys.exit(1)
    if "abc123def456" in body_text:
        print("abc123def456")
    else:
        print("rev")
    sys.exit(0)

recorded_file = None
for line in body_text.splitlines():
    if "printf \\"%s\\\\n\\" \\"$@\\" >" in line or "env >" in line:
        parts = line.split(">")
        if len(parts) > 1:
            recorded_file = parts[1].strip()

if recorded_file:
    rec_path = pathlib.Path(recorded_file)
    if "env >" in body_text:
        with open(rec_path, "w", encoding="utf-8") as f:
            for k, v in os.environ.items():
                f.write(f"{{k}}={{v}}\\n")
    else:
        with open(rec_path, "w", encoding="utf-8") as f:
            for a in args:
                f.write(f"{{a}}\\n")

dest = args[-1] if args else None
if dest and not dest.startswith("-"):
    dest_path = pathlib.Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)
    (dest_path / ("main.py" if "main.py" in body_text else "a.py")).write_text("x = 1\\n")
    if "ln -s" in body_text:
        link_target = None
        for word in body_text.split():
            if "outside" in word:
                link_target = word
        if link_target:
            try:
                (dest_path / "link").symlink_to(pathlib.Path(link_target), target_is_directory=True)
            except OSError:
                pass
sys.exit(0)
"""
    py_path = tmp_path / f"{name}_impl.py"
    py_path.write_text(py_code, encoding="utf-8")

    if sys.platform == "win32":
        bat_script = tmp_path / f"{name}.bat"
        bat_script.write_text(f'@echo off\n"{sys.executable}" "{py_path}" %*\n', encoding="utf-8")
        return bat_script
    else:
        script = tmp_path / name
        script.write_text(f'#!/bin/sh\n"{sys.executable}" "{py_path}" "$@"\n', encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return script


@pytest.fixture
def permissive_settings() -> IngestionSettings:
    return IngestionSettings(git_clone_timeout_seconds=10.0)


def test_clone_writes_working_tree_and_reports_revision(
    tmp_path, permissive_settings
):
    """Happy path: the stub materialises a file and answers rev-parse."""
    stub = _stub_git(
        tmp_path,
        'if [ "$1" = "rev-parse" ]; then echo "abc123def456"; exit 0; fi\n'
        'for arg in "$@"; do dest="$arg"; done\n'
        'mkdir -p "$dest" && printf "x = 1\\n" > "$dest/main.py"\n'
        "exit 0",
    )
    fetcher = GitRepositoryFetcher(permissive_settings, git_executable=str(stub))

    report = fetcher.fetch("https://github.com/a/b", tmp_path / "clone")

    assert report.revision == "abc123def456"
    assert report.bytes_written > 0
    assert (tmp_path / "clone" / "main.py").is_file()


def test_clone_argv_is_hardened(tmp_path, permissive_settings):
    """Shallow, single-branch, no submodules, no ext:: protocol, no symlinks."""
    recorded = tmp_path / "argv.txt"
    stub = _stub_git(
        tmp_path,
        'if [ "$1" = "rev-parse" ]; then echo rev; exit 0; fi\n'
        f'printf "%s\\n" "$@" > {recorded}\n'
        'for arg in "$@"; do dest="$arg"; done\n'
        'mkdir -p "$dest" && printf "x\\n" > "$dest/a.py"\n'
        "exit 0",
    )
    fetcher = GitRepositoryFetcher(permissive_settings, git_executable=str(stub))

    fetcher.fetch("https://github.com/a/b", tmp_path / "clone")
    argv = recorded.read_text().splitlines()

    assert "--depth" in argv and "1" in argv
    assert "--single-branch" in argv
    assert "--recurse-submodules=no" in argv
    assert "core.symlinks=false" in argv
    assert "protocol.ext.allow=never" in argv
    assert "--" in argv, "the URL must be passed after an end-of-options marker"


def test_clone_environment_disables_credential_prompts(
    tmp_path, permissive_settings, monkeypatch
):
    """A private repo must fail fast, never hang waiting for a password."""
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /root/.ssh/id_rsa")
    recorded = tmp_path / "env.txt"
    stub = _stub_git(
        tmp_path,
        'if [ "$1" = "rev-parse" ]; then echo rev; exit 0; fi\n'
        f'env > {recorded}\n'
        'for arg in "$@"; do dest="$arg"; done\n'
        'mkdir -p "$dest" && printf "x\\n" > "$dest/a.py"\n'
        "exit 0",
    )
    fetcher = GitRepositoryFetcher(permissive_settings, git_executable=str(stub))

    fetcher.fetch("https://github.com/a/b", tmp_path / "clone")
    env = dict(
        line.split("=", 1) for line in recorded.read_text().splitlines() if "=" in line
    )

    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert "GIT_SSH_COMMAND" not in env, "host SSH config must not leak into clones"


def test_clone_failure_is_reported_not_swallowed(tmp_path, permissive_settings):
    stub = _stub_git(
        tmp_path, 'echo "fatal: repository not found" >&2\nexit 128'
    )
    fetcher = GitRepositoryFetcher(permissive_settings, git_executable=str(stub))

    with pytest.raises(RepositoryFetchError) as exc_info:
        fetcher.fetch("https://github.com/a/missing", tmp_path / "clone")

    assert exc_info.value.details["exit_code"] == 128
    assert "repository not found" in exc_info.value.details["stderr"]


def test_clone_timeout_is_enforced(tmp_path):
    settings = IngestionSettings(git_clone_timeout_seconds=0.5)
    stub = _stub_git(tmp_path, "sleep 30")
    fetcher = GitRepositoryFetcher(settings, git_executable=str(stub))

    with pytest.raises(RepositoryTimeoutError):
        fetcher.fetch("https://github.com/a/b", tmp_path / "clone")


def test_missing_git_executable_is_reported_clearly(tmp_path, permissive_settings):
    fetcher = GitRepositoryFetcher(
        permissive_settings, git_executable=str(tmp_path / "no-git-here")
    )

    with pytest.raises(RepositoryFetchError, match="git executable not found"):
        fetcher.fetch("https://github.com/a/b", tmp_path / "clone")


def test_unknown_revision_when_rev_parse_fails(tmp_path, permissive_settings):
    stub = _stub_git(
        tmp_path,
        'if [ "$1" = "rev-parse" ]; then exit 1; fi\n'
        'for arg in "$@"; do dest="$arg"; done\n'
        'mkdir -p "$dest" && printf "x\\n" > "$dest/a.py"\n'
        "exit 0",
    )
    fetcher = GitRepositoryFetcher(permissive_settings, git_executable=str(stub))

    report = fetcher.fetch("https://github.com/a/b", tmp_path / "clone")

    assert report.revision == "unknown"


def test_stderr_is_scrubbed_of_credentials():
    """git echoes URLs back on failure; a token in one must not reach the log."""
    scrubbed = _sanitise("fatal: could not read Password: token=ghp_secret123 nope")
    assert "ghp_secret123" not in scrubbed
    assert "token=***" in scrubbed


def test_clone_does_not_follow_host_symlinks(tmp_path, permissive_settings):
    """Directory size accounting must not traverse a symlink out of the tree."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * 10_000)

    stub = _stub_git(
        tmp_path,
        'if [ "$1" = "rev-parse" ]; then echo rev; exit 0; fi\n'
        'for arg in "$@"; do dest="$arg"; done\n'
        'mkdir -p "$dest" && printf "x\\n" > "$dest/a.py"\n'
        f'ln -s {outside} "$dest/link"\n'
        "exit 0",
    )
    fetcher = GitRepositoryFetcher(permissive_settings, git_executable=str(stub))

    report = fetcher.fetch("https://github.com/a/b", tmp_path / "clone")

    assert report.bytes_written < 1000, "symlinked content must not be counted"


def test_source_file_limit_stops_the_scan(tmp_path, ingestion_settings):
    """A runaway monorepo must not exhaust memory during the walk."""
    from codesmell.core.enums import RejectionReason, SourceKind
    from codesmell.ingestion.inventory import ProjectInventoryBuilder

    tight = ingestion_settings.model_copy(update={"max_source_files": 3})
    root = tmp_path / "many"
    root.mkdir()
    for index in range(10):
        (root / f"mod_{index}.py").write_text(f"x = {index}\n", encoding="utf-8")

    inventory = ProjectInventoryBuilder(tight).build(
        root, name="many", source_kind=SourceKind.DIRECTORY
    )

    assert inventory.file_count == 3
    assert any(
        r.reason is RejectionReason.MEMBER_LIMIT for r in inventory.rejections
    )


# --------------------------------------------------------------------- #
# analyze command
# --------------------------------------------------------------------- #


def _clear_settings_cache():
    from codesmell.config.settings import get_settings

    get_settings.cache_clear()


def test_analyze_command_reports_class_metrics(sample_project, tmp_path, monkeypatch):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    result = runner.invoke(app, ["analyze", str(sample_project), "--type", "class"])

    assert result.exit_code == 0
    assert "OrderService" in result.stdout
    assert "wmc" in result.stdout
    _clear_settings_cache()


def test_analyze_command_supports_method_view(sample_project, tmp_path, monkeypatch):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    result = runner.invoke(
        app,
        ["analyze", str(sample_project), "--type", "method", "--sort",
         "cognitive_complexity"],
    )

    assert result.exit_code == 0
    assert "place" in result.stdout
    _clear_settings_cache()


def test_analyze_command_rejects_unknown_entity_type(
    sample_project, tmp_path, monkeypatch
):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    result = runner.invoke(app, ["analyze", str(sample_project), "--type", "widget"])

    assert result.exit_code == 2
    assert "unknown entity type" in result.stdout
    _clear_settings_cache()


def test_analyze_command_falls_back_on_unknown_sort_metric(
    sample_project, tmp_path, monkeypatch
):
    """An unusable sort key must degrade to a usable report, not an error."""
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    result = runner.invoke(
        app, ["analyze", str(sample_project), "--sort", "not_a_metric"]
    )

    assert result.exit_code == 0
    assert "unknown metric" in result.stdout
    _clear_settings_cache()


def test_analyze_command_exits_nonzero_on_bad_source(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    result = runner.invoke(app, ["analyze", "/no/such/path"])

    assert result.exit_code == 1
    _clear_settings_cache()


# --------------------------------------------------------------------- #
# detect command
# --------------------------------------------------------------------- #


def test_detect_command_runs_end_to_end(sample_project, tmp_path, monkeypatch):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    result = runner.invoke(app, ["detect", str(sample_project)])

    assert result.exit_code == 0
    assert "Detection summary" in result.stdout
    assert "absolute" in result.stdout
    _clear_settings_cache()


def test_detect_command_supports_percentile_mode(
    sample_project, tmp_path, monkeypatch
):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    result = runner.invoke(
        app, ["detect", str(sample_project), "--thresholds", "percentile"]
    )

    assert result.exit_code == 0
    assert "percentile" in result.stdout
    _clear_settings_cache()


def test_detect_command_rejects_unknown_threshold_mode(
    sample_project, tmp_path, monkeypatch
):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    result = runner.invoke(
        app, ["detect", str(sample_project), "--thresholds", "vibes"]
    )

    assert result.exit_code == 2
    assert "unknown threshold mode" in result.stdout
    _clear_settings_cache()


def test_detect_command_rejects_unknown_severity(
    sample_project, tmp_path, monkeypatch
):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    result = runner.invoke(
        app, ["detect", str(sample_project), "--min-severity", "catastrophic"]
    )

    assert result.exit_code == 2
    _clear_settings_cache()


def test_detect_command_explain_shows_the_condition_trail(
    tmp_path, monkeypatch
):
    """The explanation must name the metric, the threshold and the verdict --
    a detector that cannot justify itself is useless as a paper baseline."""
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    project = tmp_path / "proj"
    project.mkdir()
    body = "\n".join(f"    x{i} = {i}" for i in range(3))
    (project / "m.py").write_text(
        "class Chain:\n"
        "    def __init__(self):\n        self.root = None\n\n"
        "    def dig(self):\n"
        "        return self.root.a.b.c.d.e\n" + body + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["detect", str(project), "--explain"])

    assert result.exit_code == 0
    assert "max_message_chain" in result.stdout
    _clear_settings_cache()


def test_detect_command_exits_nonzero_on_bad_source(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    _clear_settings_cache()

    result = runner.invoke(app, ["detect", "/no/such/path"])

    assert result.exit_code == 1
    _clear_settings_cache()
