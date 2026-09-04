"""Path and content filtering.

Analysing a virtualenv or a vendored dependency tree pollutes every downstream
metric: site-packages will dominate the project's LOC distribution and any
project-relative feature scaling computed over it is meaningless.

Directory exclusion is deliberately conservative. ``bin`` and ``lib`` are *not*
blanket-excluded because they are legitimate Python package names -- they are
only excluded when they sit inside a detected virtual environment.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

from codesmell.core.enums import Language, RejectionReason
from codesmell.core.models import Rejection

#: Directory names that never contain first-party source.
DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        # VCS and tooling
        ".git", ".hg", ".svn", ".idea", ".vscode",
        # Python caches and build artefacts
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".tox", ".nox", ".eggs", "build", "dist", "site-packages",
        # Virtual environments (also detected structurally via pyvenv.cfg)
        "venv", ".venv", "env", ".env", "virtualenv", "envs",
        # JS / other ecosystems that may be vendored into a Python repo
        "node_modules", "bower_components", "vendor", "third_party",
        # JVM build output, for when the Java adapter lands at M2b
        "target", "out", ".gradle",
        # Coverage and docs output
        "htmlcov", "_build", ".next", ".cache",
    }
)

#: Filename suffixes that are source but not first-party.
DEFAULT_EXCLUDED_SUFFIXES: frozenset[str] = frozenset(
    {".min.py", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".class", ".jar"}
)

#: Filename fragments marking machine-generated source.
DEFAULT_GENERATED_MARKERS: tuple[str, ...] = (
    "_pb2.py", "_pb2_grpc.py", "_generated.py", ".g.py", "_ui.py",
)

#: Extension -> language. Extend here when a new parser adapter is registered.
LANGUAGE_BY_SUFFIX: dict[str, Language] = {
    # Python
    ".py": Language.PYTHON,
    ".pyi": Language.PYTHON,
    # Java & Kotlin
    ".java": Language.JAVA,
    ".kt": Language.KOTLIN,
    ".kts": Language.KOTLIN,
    # JavaScript / TypeScript / Web
    ".js": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
    ".mjs": Language.JAVASCRIPT,
    ".cjs": Language.JAVASCRIPT,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT,
    ".html": Language.HTML,
    ".htm": Language.HTML,
    ".css": Language.CSS,
    ".scss": Language.CSS,
    ".less": Language.CSS,
    # C / C++ / C#
    ".c": Language.C,
    ".h": Language.C,
    ".cpp": Language.CPP,
    ".cxx": Language.CPP,
    ".cc": Language.CPP,
    ".hpp": Language.CPP,
    ".cs": Language.CSHARP,
    # Go / Rust / Swift / Ruby / PHP
    ".go": Language.GO,
    ".rs": Language.RUST,
    ".swift": Language.SWIFT,
    ".rb": Language.RUBY,
    ".php": Language.PHP,
    # Shell / SQL / Data / Config
    ".sh": Language.OTHER,
    ".bash": Language.OTHER,
    ".zsh": Language.OTHER,
    ".ps1": Language.OTHER,
    ".sql": Language.OTHER,
    ".json": Language.OTHER,
    ".toml": Language.OTHER,
    ".yaml": Language.OTHER,
    ".yml": Language.OTHER,
    ".xml": Language.OTHER,
    ".md": Language.OTHER,
    ".txt": Language.OTHER,
}

_NULL_SNIFF_BYTES = 8192


@dataclass(frozen=True, slots=True)
class PathFilter:
    """Decides which files reach the parser.

    Immutable; use :meth:`with_extra_excluded_dirs` to derive a variant rather
    than mutating a shared instance.
    """

    excluded_dirs: frozenset[str] = DEFAULT_EXCLUDED_DIRS
    excluded_suffixes: frozenset[str] = DEFAULT_EXCLUDED_SUFFIXES
    generated_markers: tuple[str, ...] = DEFAULT_GENERATED_MARKERS
    #: Languages the *inventory* records. Deliberately every known language,
    #: not only the parseable ones: a Java project must be reported as a Java
    #: project with a clear "no parser adapter" warning, rather than failing
    #: with a misleading "no source files found". The supported/unsupported
    #: distinction belongs to the parser layer, not the census.
    languages: frozenset[Language] = field(default_factory=Language.supported)
    max_file_bytes: int = 4 * 1024 * 1024
    include_tests: bool = True

    def with_extra_excluded_dirs(self, names: Iterable[str]) -> PathFilter:
        return replace(self, excluded_dirs=self.excluded_dirs | frozenset(names))

    # ------------------------------------------------------------------ #
    # Directory-level
    # ------------------------------------------------------------------ #

    def should_skip_dir(self, name: str) -> bool:
        """Whether to prune a directory during the walk."""
        if name in self.excluded_dirs:
            return True
        if name.startswith(".") and name not in (".", ".."):
            return True
        return name.endswith(".egg-info")

    @staticmethod
    def is_virtualenv(directory: Path) -> bool:
        """Structural virtualenv detection, independent of directory name.

        Catches environments named something other than ``venv`` -- which is
        common enough that name-based exclusion alone misses them.
        """
        return (directory / "pyvenv.cfg").is_file() or (
            (directory / "bin" / "activate").is_file()
            and (directory / "lib").is_dir()
        )

    # ------------------------------------------------------------------ #
    # File-level
    # ------------------------------------------------------------------ #

    def language_of(self, relative_path: str) -> Language:
        suffix = PurePosixPath(relative_path.replace("\\", "/")).suffix.lower()
        if not suffix:
            return Language.OTHER
        return LANGUAGE_BY_SUFFIX.get(suffix, Language.OTHER)

    def screen(self, relative_path: str, size_bytes: int) -> Rejection | None:
        """Return a :class:`Rejection` if the file must not be analysed."""
        posix = PurePosixPath(relative_path.replace("\\", "/"))
        name = posix.name

        for part in posix.parts[:-1]:
            if self.should_skip_dir(part):
                return Rejection(
                    relative_path, RejectionReason.EXCLUDED_PATH, f"in {part}/"
                )

        lowered = name.lower()
        if any(lowered.endswith(s) for s in self.excluded_suffixes):
            return Rejection(relative_path, RejectionReason.DISALLOWED_SUFFIX)

        if any(marker in lowered for marker in self.generated_markers):
            return Rejection(
                relative_path, RejectionReason.EXCLUDED_PATH, "generated source"
            )

        language = self.language_of(relative_path)
        if language not in self.languages:
            return Rejection(
                relative_path,
                RejectionReason.DISALLOWED_SUFFIX,
                f"language {language.value}",
            )

        if not self.include_tests and self._is_test_path(posix):
            return Rejection(
                relative_path, RejectionReason.EXCLUDED_PATH, "test code"
            )

        if size_bytes > self.max_file_bytes:
            return Rejection(
                relative_path,
                RejectionReason.MEMBER_TOO_LARGE,
                f"{size_bytes} > {self.max_file_bytes}",
            )

        return None

    @staticmethod
    def _is_test_path(posix: PurePosixPath) -> bool:
        name = posix.name.lower()
        if name.startswith("test_") or name.endswith("_test.py"):
            return True
        return any(part.lower() in ("test", "tests") for part in posix.parts[:-1])


def looks_binary(path: Path, sniff_bytes: int = _NULL_SNIFF_BYTES) -> bool:
    """Heuristic binary check: a NUL byte in the first block.

    Cheaper and more reliable than extension checks for files that lie about
    their type, and it costs one short read per file.
    """
    try:
        with path.open("rb") as handle:
            return b"\0" in handle.read(sniff_bytes)
    except OSError:
        return True


def read_source(path: Path) -> str | None:
    """Read a source file as UTF-8, returning ``None`` if it is not decodable.

    Real repositories contain latin-1 and cp1252 files. Returning ``None``
    rather than raising keeps one bad file from aborting a whole analysis.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def count_lines(text: str) -> int:
    """Physical line count, counting a trailing newline as terminating a line."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def sorted_rejections(rejections: Sequence[Rejection]) -> tuple[Rejection, ...]:
    """Deterministic ordering, so reports and fixtures are stable."""
    return tuple(sorted(rejections, key=lambda r: (r.reason.value, r.path)))
