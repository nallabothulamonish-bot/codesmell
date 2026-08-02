"""Filtering and detection tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesmell.core.enums import BuildTool, Language, RejectionReason
from codesmell.core.models import SourceFile
from codesmell.ingestion.detection import (
    BuildToolDetector,
    DependencyDetector,
    FrameworkDetector,
    LanguageDetector,
)
from codesmell.ingestion.filters import (
    PathFilter,
    count_lines,
    looks_binary,
    read_source,
)

# --------------------------------------------------------------------- #
# PathFilter
# --------------------------------------------------------------------- #


@pytest.fixture
def path_filter() -> PathFilter:
    return PathFilter(max_file_bytes=1024)


@pytest.mark.parametrize(
    "name",
    ["__pycache__", "node_modules", ".git", "build", "dist", "venv", ".venv"],
)
def test_skips_known_noise_directories(path_filter: PathFilter, name: str):
    assert path_filter.should_skip_dir(name)


@pytest.mark.parametrize("name", ["src", "app", "core", "lib", "bin", "tests"])
def test_does_not_skip_legitimate_package_names(path_filter: PathFilter, name: str):
    """``lib`` and ``bin`` are valid Python packages; only venvs exclude them."""
    assert not path_filter.should_skip_dir(name)


def test_skips_egg_info_directories(path_filter: PathFilter):
    assert path_filter.should_skip_dir("sample.egg-info")


def test_detects_virtualenv_structurally(tmp_path: Path):
    """A venv named anything at all is still a venv."""
    env = tmp_path / "my-weird-env-name"
    env.mkdir()
    (env / "pyvenv.cfg").write_text("home = /usr\n")
    assert PathFilter.is_virtualenv(env)


def test_plain_directory_is_not_a_virtualenv(tmp_path: Path):
    plain = tmp_path / "src"
    plain.mkdir()
    assert not PathFilter.is_virtualenv(plain)


def test_accepts_ordinary_python_module(path_filter: PathFilter):
    assert path_filter.screen("src/app/service.py", 500) is None


def test_rejects_unsupported_language(path_filter: PathFilter):
    verdict = path_filter.screen("src/app/main.go", 500)
    assert verdict is not None
    assert verdict.reason is RejectionReason.DISALLOWED_SUFFIX


def test_rejects_generated_protobuf_module(path_filter: PathFilter):
    verdict = path_filter.screen("src/app/schema_pb2.py", 500)
    assert verdict is not None
    assert verdict.reason is RejectionReason.EXCLUDED_PATH


def test_rejects_file_over_size_limit(path_filter: PathFilter):
    verdict = path_filter.screen("src/app/huge.py", 999_999)
    assert verdict is not None
    assert verdict.reason is RejectionReason.MEMBER_TOO_LARGE


def test_rejects_file_inside_excluded_directory(path_filter: PathFilter):
    verdict = path_filter.screen("node_modules/pkg/index.py", 100)
    assert verdict is not None
    assert verdict.reason is RejectionReason.EXCLUDED_PATH


def test_test_code_included_by_default(path_filter: PathFilter):
    assert path_filter.screen("tests/test_service.py", 100) is None


def test_test_code_excluded_when_configured():
    strict = PathFilter(include_tests=False, max_file_bytes=1024)
    verdict = strict.screen("tests/test_service.py", 100)
    assert verdict is not None
    assert verdict.reason is RejectionReason.EXCLUDED_PATH


def test_language_resolved_from_suffix(path_filter: PathFilter):
    assert path_filter.language_of("a/b.py") is Language.PYTHON
    assert path_filter.language_of("a/B.java") is Language.JAVA
    assert path_filter.language_of("a/b.txt") is Language.UNKNOWN


# --------------------------------------------------------------------- #
# Content helpers
# --------------------------------------------------------------------- #


def test_binary_content_detected_by_null_byte(tmp_path: Path):
    binary = tmp_path / "blob.py"
    binary.write_bytes(b"import os\x00\x01\x02")
    assert looks_binary(binary)


def test_plain_source_is_not_binary(tmp_path: Path):
    source = tmp_path / "mod.py"
    source.write_text("def f():\n    return 1\n")
    assert not looks_binary(source)


def test_latin1_source_is_read_not_dropped(tmp_path: Path):
    """Real repos contain non-UTF-8 files; one must not abort the analysis."""
    path = tmp_path / "legacy.py"
    path.write_bytes("# caf\xe9 comment\nx = 1\n".encode("latin-1"))
    text = read_source(path)
    assert text is not None
    assert "x = 1" in text


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("a", 1), ("a\n", 1), ("a\nb", 2), ("a\nb\n", 2), ("\n\n", 2)],
)
def test_line_counting(text: str, expected: int):
    assert count_lines(text) == expected


# --------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------- #


def _source_file(path: str, language: Language, size: int) -> SourceFile:
    return SourceFile(
        relative_path=path,
        language=language,
        size_bytes=size,
        line_count=max(1, size // 30),
        sha256="0" * 64,
    )


def test_primary_language_weighted_by_bytes_not_file_count():
    """Forty tiny __init__.py files must not outvote substantial Java code."""
    files = [
        *(_source_file(f"p/{i}/__init__.py", Language.PYTHON, 10) for i in range(40)),
        _source_file("Main.java", Language.JAVA, 50_000),
    ]
    assert LanguageDetector().primary(files) is Language.JAVA


def test_primary_language_is_unknown_for_empty_project():
    assert LanguageDetector().primary([]) is Language.UNKNOWN


def test_language_counts_are_per_file():
    files = [
        _source_file("a.py", Language.PYTHON, 100),
        _source_file("b.py", Language.PYTHON, 100),
        _source_file("C.java", Language.JAVA, 100),
    ]
    counts = LanguageDetector().counts(files)
    assert counts == {Language.PYTHON: 2, Language.JAVA: 1}


def test_detects_poetry_from_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry]\nname = 'x'\n", encoding="utf-8"
    )
    assert BuildTool.POETRY in BuildToolDetector().detect(tmp_path)


def test_detects_pep621_setuptools_from_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'x'\nversion = '1'\n", encoding="utf-8"
    )
    assert BuildTool.SETUPTOOLS in BuildToolDetector().detect(tmp_path)


def test_detects_pip_from_requirements_variants(tmp_path: Path):
    (tmp_path / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
    assert BuildTool.PIP in BuildToolDetector().detect(tmp_path)


def test_unknown_when_no_marker_present(tmp_path: Path):
    """No evidence means UNKNOWN -- never a plausible-looking guess."""
    assert BuildToolDetector().detect(tmp_path) == (BuildTool.UNKNOWN,)


def test_malformed_pyproject_does_not_crash_detection(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[[[not toml", encoding="utf-8")
    assert BuildToolDetector().detect(tmp_path) == (BuildTool.UNKNOWN,)


def test_dependencies_parsed_from_requirements(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "# comment\npandas==2.1.0\nnumpy>=1.24\n-r other.txt\n\n",
        encoding="utf-8",
    )
    assert set(DependencyDetector().detect(tmp_path)) == {"pandas", "numpy"}


def test_dependencies_parsed_from_poetry_section(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry.dependencies]\npython = '^3.11'\nfastapi = '^0.110'\n",
        encoding="utf-8",
    )
    deps = DependencyDetector().detect(tmp_path)
    assert "fastapi" in deps
    assert "python" not in deps, "the interpreter is not a dependency"


def test_frameworks_mapped_from_dependencies():
    labels = FrameworkDetector().detect(["fastapi", "sqlalchemy", "leftpad"])
    assert labels == ("FastAPI", "SQLAlchemy")
