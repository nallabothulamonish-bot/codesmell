"""Language, build-tool and dependency detection.

Detection is evidence-based and never guesses beyond what it can see. If no
marker file exists, the build tool is ``UNKNOWN`` rather than a plausible
default -- an invented value here would propagate into the project metadata
reported in the paper.
"""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from codesmell.config.logging import get_logger
from codesmell.core.enums import BuildTool, Language
from codesmell.core.models import SourceFile

logger = get_logger(__name__)

#: Marker filename -> build tool, for markers that are unambiguous on sight.
_SIMPLE_MARKERS: dict[str, BuildTool] = {
    "Pipfile": BuildTool.PIPENV,
    "setup.py": BuildTool.SETUPTOOLS,
    "setup.cfg": BuildTool.SETUPTOOLS,
    "environment.yml": BuildTool.CONDA,
    "environment.yaml": BuildTool.CONDA,
    "pom.xml": BuildTool.MAVEN,
    "build.gradle": BuildTool.GRADLE,
    "build.gradle.kts": BuildTool.GRADLE,
}

_REQUIREMENTS_RE = re.compile(r"^requirements.*\.txt$", re.IGNORECASE)

#: PEP 508 requirement -> distribution name.
_REQUIREMENT_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")

#: Import name -> framework label, for the frameworks worth reporting.
_FRAMEWORK_BY_DISTRIBUTION: dict[str, str] = {
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "pyramid": "Pyramid",
    "tornado": "Tornado",
    "aiohttp": "aiohttp",
    "sqlalchemy": "SQLAlchemy",
    "pandas": "pandas",
    "numpy": "NumPy",
    "scikit-learn": "scikit-learn",
    "torch": "PyTorch",
    "tensorflow": "TensorFlow",
    "pytest": "pytest",
    "celery": "Celery",
    "scrapy": "Scrapy",
}


class LanguageDetector:
    """Determines the primary language by weight of source bytes.

    Byte weight rather than file count: a project with three hundred tiny
    ``__init__.py`` files and forty substantial Java classes is a Java project.
    """

    def counts(self, source_files: Sequence[SourceFile]) -> dict[Language, int]:
        counter: Counter[Language] = Counter()
        for source_file in source_files:
            counter[source_file.language] += 1
        return dict(counter)

    def primary(self, source_files: Sequence[SourceFile]) -> Language:
        if not source_files:
            return Language.UNKNOWN

        weights: Counter[Language] = Counter()
        for source_file in source_files:
            if source_file.language is Language.UNKNOWN:
                continue
            weights[source_file.language] += source_file.size_bytes

        if not weights:
            return Language.UNKNOWN

        # Sort by (bytes desc, language name) so ties resolve deterministically.
        best = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0].value))
        return best[0][0]


class BuildToolDetector:
    """Identifies build tools from marker files in the project root."""

    def detect(self, root: Path) -> tuple[BuildTool, ...]:
        found: list[BuildTool] = []

        try:
            entries = list(root.iterdir())
        except OSError:
            return ()

        names = {entry.name for entry in entries if entry.is_file()}

        for marker, tool in _SIMPLE_MARKERS.items():
            if marker in names and tool not in found:
                found.append(tool)

        if (
            any(_REQUIREMENTS_RE.match(name) for name in names)
            and BuildTool.PIP not in found
        ):
            found.append(BuildTool.PIP)

        if "pyproject.toml" in names:
            for tool in self._from_pyproject(root / "pyproject.toml"):
                if tool not in found:
                    found.append(tool)

        return tuple(found) if found else (BuildTool.UNKNOWN,)

    def _from_pyproject(self, path: Path) -> tuple[BuildTool, ...]:
        data = _load_toml(path)
        if data is None:
            return ()

        tools = data.get("tool", {})
        detected: list[BuildTool] = []
        if isinstance(tools, dict):
            if "poetry" in tools:
                detected.append(BuildTool.POETRY)
            if "pdm" in tools:
                detected.append(BuildTool.PDM)
            if "hatch" in tools:
                detected.append(BuildTool.HATCH)

        if not detected and "project" in data:
            detected.append(BuildTool.SETUPTOOLS)

        return tuple(detected)


class DependencyDetector:
    """Extracts declared dependency names from the project's manifests.

    Names only -- version constraints are deliberately dropped, because the
    inventory is used for reporting and framework detection, not resolution.
    """

    def detect(self, root: Path) -> tuple[str, ...]:
        names: set[str] = set()

        for entry in _safe_iterdir(root):
            if entry.is_file() and _REQUIREMENTS_RE.match(entry.name):
                names.update(self._from_requirements(entry))

        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            names.update(self._from_pyproject(pyproject))

        return tuple(sorted(names))

    def _from_requirements(self, path: Path) -> set[str]:
        names: set[str] = set()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return names

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("#", "-", "$", "http:", "https:")):
                continue
            match = _REQUIREMENT_NAME_RE.match(line)
            if match:
                names.add(match.group(1).lower())
        return names

    def _from_pyproject(self, path: Path) -> set[str]:
        data = _load_toml(path)
        if data is None:
            return set()

        names: set[str] = set()

        project = data.get("project", {})
        if isinstance(project, dict):
            for entry in project.get("dependencies", []) or []:
                if isinstance(entry, str):
                    match = _REQUIREMENT_NAME_RE.match(entry)
                    if match:
                        names.add(match.group(1).lower())

        poetry = data.get("tool", {}).get("poetry", {})
        if isinstance(poetry, dict):
            for key in poetry.get("dependencies", {}) or {}:
                if key.lower() != "python":
                    names.add(key.lower())

        return names


class FrameworkDetector:
    """Maps declared dependencies to human-readable framework labels."""

    def detect(self, dependencies: Sequence[str]) -> tuple[str, ...]:
        labels = {
            _FRAMEWORK_BY_DISTRIBUTION[name]
            for name in (d.lower() for d in dependencies)
            if name in _FRAMEWORK_BY_DISTRIBUTION
        }
        return tuple(sorted(labels))


def _load_toml(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning(
            "unreadable manifest", extra={"path": path.name, "error": str(exc)}
        )
        return None


def _safe_iterdir(root: Path) -> list[Path]:
    try:
        return list(root.iterdir())
    except OSError:
        return []
