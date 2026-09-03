"""Domain models.

Pure data. No I/O, no framework types, no database concerns. Everything here is
frozen so that a value handed to a worker, a detector or an explainer cannot be
mutated behind the caller's back.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from codesmell.core.enums import (
    BuildTool,
    EntityType,
    Language,
    RejectionReason,
    Severity,
    SmellType,
    SourceKind,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Rejection:
    """A file or archive member that was refused, with the reason why."""

    path: str
    reason: RejectionReason
    detail: str = ""

    def __str__(self) -> str:
        suffix = f" ({self.detail})" if self.detail else ""
        return f"{self.path}: {self.reason.value}{suffix}"


@dataclass(frozen=True, slots=True)
class SourceFile:
    """One analysable source file inside an ingested project.

    ``relative_path`` is always POSIX-style and relative to the project root, so
    it is stable across operating systems and safe to persist as an identifier.
    """

    relative_path: str
    language: Language
    size_bytes: int
    line_count: int
    sha256: str

    def __post_init__(self) -> None:
        if PurePosixPath(self.relative_path).is_absolute():
            raise ValueError(f"relative_path must be relative: {self.relative_path!r}")
        if self.size_bytes < 0 or self.line_count < 0:
            raise ValueError("size_bytes and line_count must be non-negative")

    @property
    def name(self) -> str:
        return PurePosixPath(self.relative_path.replace("\\", "/")).name

    @property
    def package_path(self) -> str:
        """Dotted package path, e.g. ``pkg/sub/mod.py`` -> ``pkg.sub.mod``."""
        p = PurePosixPath(self.relative_path.replace("\\", "/"))
        parts = list(p.parent.parts) if str(p.parent) != "." else []
        stem = p.stem
        if stem != "__init__":
            parts.append(stem)
        return ".".join(parts)


@dataclass(frozen=True, slots=True)
class ProjectInventory:
    """The structural census of an ingested project.

    Produced by M1 and consumed by every later stage: the parser iterates
    ``source_files``, the metrics engine builds its symbol table from them, and
    the dataset layer uses ``fingerprint`` to key cached feature extractions.
    """

    name: str
    source_kind: SourceKind
    primary_language: Language
    languages: Mapping[Language, int]
    build_tools: Sequence[BuildTool]
    source_files: Sequence[SourceFile]
    dependencies: Sequence[str] = ()
    rejections: Sequence[Rejection] = ()
    scanned_at: datetime = field(default_factory=_utcnow)
    origin: str = ""

    @property
    def file_count(self) -> int:
        return len(self.source_files)

    @property
    def total_bytes(self) -> int:
        return sum(f.size_bytes for f in self.source_files)

    @property
    def total_lines(self) -> int:
        return sum(f.line_count for f in self.source_files)

    def files_for(self, language: Language) -> tuple[SourceFile, ...]:
        return tuple(f for f in self.source_files if f.language is language)

    @property
    def fingerprint(self) -> str:
        """Content hash of the project, independent of file ordering.

        Two ingests of the same source tree produce the same fingerprint, which
        is what makes feature-extraction caching correct rather than merely
        fast. Path is included so a renamed file invalidates the cache.
        """
        import hashlib

        digest = hashlib.sha256()
        for f in sorted(self.source_files, key=lambda s: s.relative_path):
            digest.update(f.relative_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(f.sha256.encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_kind": self.source_kind.value if hasattr(self.source_kind, "value") else str(self.source_kind),
            "primary_language": self.primary_language.value if hasattr(self.primary_language, "value") else str(self.primary_language),
            "languages": { (k.value if hasattr(k, "value") else str(k)): v for k, v in self.languages.items() },
            "build_tools": [b.value if hasattr(b, "value") else str(b) for b in self.build_tools],
            "file_count": self.file_count,
            "total_lines": self.total_lines,
            "total_bytes": self.total_bytes,
            "dependency_count": len(self.dependencies),
            "rejection_count": len(self.rejections),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class CodeEntity:
    """A class, method, function or module -- the unit a prediction attaches to.

    Populated by the parser adapters at M2. Declared here because the ports in
    :mod:`codesmell.core.ports` reference it, and ports must not depend on any
    concrete adapter.
    """

    entity_id: str
    entity_type: EntityType
    name: str
    qualified_name: str
    relative_path: str
    start_line: int
    end_line: int
    language: Language
    parent_qualified_name: str | None = None

    def __post_init__(self) -> None:
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line {self.end_line} precedes start_line {self.start_line} "
                f"for {self.qualified_name!r}"
            )

    @property
    def line_span(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass(frozen=True, slots=True)
class EntityFacts:
    """Structural facts the parser extracted about one entity.

    Deliberately language-agnostic: every field names a concept that exists in
    any object-oriented language, so the metrics engine can compute coupling,
    cohesion and inheritance metrics without importing a language adapter.
    The parser is responsible for translating its own AST into these terms.
    """

    references: tuple[str, ...] = ()
    """Names referenced anywhere inside the entity."""

    called_names: tuple[str, ...] = ()
    """Function or method names invoked, in call order (duplicates kept)."""

    accessed_fields: tuple[str, ...] = ()
    """Own instance fields read or written -- the input to LCOM."""

    base_names: tuple[str, ...] = ()
    """Declared superclasses, as written in the source. Classes only."""

    declared_fields: tuple[str, ...] = ()
    """Fields declared by this entity. Classes only."""

    decorators: tuple[str, ...] = ()

    parameter_count: int = 0
    """Declared parameters, ``self``/``cls`` included."""

    has_self_parameter: bool = False


@dataclass(frozen=True, slots=True)
class ParsedModule:
    """Everything one parsed source file contributes to the analysis.

    ``native_nodes`` holds language-specific AST nodes keyed by entity id. It is
    typed as ``Any`` on purpose: :mod:`codesmell.core` must not import
    :mod:`ast` or ``javalang``. Only metric calculators registered for the same
    language may interpret it, which the engine enforces.
    """

    source_file: SourceFile
    entities: Sequence[CodeEntity] = ()
    facts: Mapping[str, EntityFacts] = field(default_factory=dict)
    native_nodes: Mapping[str, Any] = field(default_factory=dict)
    imports: Mapping[str, str] = field(default_factory=dict)
    parse_error: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.parse_error)

    def facts_for(self, entity: CodeEntity) -> EntityFacts:
        return self.facts.get(entity.entity_id, EntityFacts())


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """Computed metrics for one entity.

    ``entity_type`` travels with the vector because class and method feature
    spaces are disjoint and must never be concatenated by accident.
    """

    entity_id: str
    entity_type: EntityType
    values: Mapping[str, float]

    def __getitem__(self, key: str) -> float:
        return self.values[key]

    def get(self, key: str, default: float = 0.0) -> float:
        return self.values.get(key, default)

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.values))


@dataclass(frozen=True, slots=True)
class SmellPrediction:
    """One model output, with everything the UI and the report need."""

    entity_id: str
    smell_type: SmellType
    is_present: bool
    confidence: float
    severity: Severity = Severity.NONE
    model_name: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")
        if not self.is_present and self.severity is not Severity.NONE:
            raise ValueError("absent smell cannot carry a non-NONE severity")


@dataclass(frozen=True, slots=True)
class ExtractionReport:
    """Outcome of unpacking an archive."""

    files_written: int
    bytes_written: int
    rejections: Sequence[Rejection] = ()


@dataclass(frozen=True, slots=True)
class FetchReport:
    """Outcome of cloning a remote repository."""

    url: str
    revision: str
    bytes_written: int


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """What :class:`~codesmell.ingestion.service.IngestionService` returns."""

    inventory: ProjectInventory
    root: Any  # pathlib.Path; typed loosely to keep this module I/O-free
    warnings: Sequence[str] = ()
