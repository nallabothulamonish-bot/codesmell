"""Abstract ports (hexagonal architecture).

These are the seams the spec's extensibility requirement rests on. Adding a
language, a metric, a smell detector or an explainability technique means
writing one class here-conformant and adding one registry entry -- never
editing downstream code.

Nothing in this module performs I/O or imports a concrete adapter.

.. note::
   :class:`SourceParser` and :class:`AnalysisContext` were revised at M2. The
   M0 declarations returned a bare sequence of entities -- written before the
   metrics engine's requirements were concrete. Coupling metrics need the
   cross-file reference graph and cohesion metrics need per-method field
   access, and neither survives a flat entity list. The port now returns a
   :class:`~codesmell.core.models.ParsedModule`. Recorded here rather than
   quietly rewritten, because this interface is what every later milestone is
   built against.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from codesmell.core.enums import EntityType, Language, SmellType
from codesmell.core.models import (
    CodeEntity,
    EntityFacts,
    ExtractionReport,
    FeatureVector,
    FetchReport,
    ParsedModule,
    ProjectInventory,
    SmellPrediction,
    SourceFile,
)


class ArchiveExtractor(ABC):
    """Unpacks a user-supplied archive into a sandboxed destination."""

    @abstractmethod
    def supports(self, archive_path: Path) -> bool:
        """Whether this extractor recognises the archive format."""

    @abstractmethod
    def extract(self, archive_path: Path, destination: Path) -> ExtractionReport:
        """Unpack ``archive_path`` into ``destination``.

        Implementations MUST guarantee that no byte is written outside
        ``destination`` and MUST enforce the configured member-count, member
        size, total size and compression-ratio limits.
        """


class RepositoryFetcher(ABC):
    """Fetches a remote repository into a sandboxed destination."""

    @abstractmethod
    def supports(self, url: str) -> bool:
        """Whether this fetcher can handle the URL scheme and host."""

    @abstractmethod
    def fetch(self, url: str, destination: Path) -> FetchReport:
        """Clone ``url`` into ``destination``.

        Implementations MUST validate the URL before touching the network and
        MUST NOT execute any code contained in the repository.
        """


class SourceParser(ABC):
    """Builds a language-specific AST and extracts entities and facts from it."""

    @property
    @abstractmethod
    def language(self) -> Language:
        """The language this parser handles."""

    @abstractmethod
    def parse(self, source: str, source_file: SourceFile) -> ParsedModule:
        """Parse ``source`` into entities, structural facts and native nodes.

        Must not raise on syntactically invalid input: return a
        :class:`~codesmell.core.models.ParsedModule` with ``parse_error`` set
        instead, so one unparseable file cannot abort a thousand-file analysis.
        """


class MetricCalculator(ABC):
    """Computes one or more named metrics for entities of a given type.

    Registered as a plugin. ``metric_names`` is used to build the feature
    registry, so the same calculator serves training and inference by
    construction -- the feature-parity guarantee from the roadmap, section 1.3.
    """

    @property
    @abstractmethod
    def language(self) -> Language:
        """Language whose native nodes this calculator understands."""

    @property
    @abstractmethod
    def metric_names(self) -> tuple[str, ...]:
        """Stable names of the metrics this calculator emits."""

    @property
    @abstractmethod
    def applies_to(self) -> frozenset[EntityType]:
        """Entity types this calculator is defined for."""

    @abstractmethod
    def compute(
        self, entity: CodeEntity, context: AnalysisContext
    ) -> dict[str, float]:
        """Compute metrics for one entity.

        ``context`` provides the cross-file symbol table required by coupling
        metrics such as CBO, RFC and fan-in, which cannot be derived from a
        single file.

        Must return a value for every name in :attr:`metric_names`. A missing
        key would produce a ragged feature matrix and a silent NaN at training
        time, so the engine treats it as a hard error.
        """


@runtime_checkable
class AnalysisContext(Protocol):
    """Read-only cross-file view handed to metric calculators.

    A Protocol rather than an ABC: the metrics engine supplies the concrete
    implementation at M2, and calculators only need structural conformance.
    """

    @property
    def inventory(self) -> ProjectInventory: ...

    def entities(self) -> Iterable[CodeEntity]: ...

    def entity_by_id(self, entity_id: str) -> CodeEntity | None: ...

    def entity_by_qualified_name(self, qualified_name: str) -> CodeEntity | None: ...

    def facts(self, entity: CodeEntity) -> EntityFacts: ...

    def native_node(self, entity: CodeEntity) -> Any: ...

    def imports_for(self, entity: CodeEntity) -> Mapping[str, str]:
        """Import bindings visible in the entity's module."""
        ...

    def source_of(self, entity: CodeEntity) -> str:
        """The exact source text of this entity, first line to last."""
        ...

    def children_of(self, entity: CodeEntity) -> Sequence[CodeEntity]:
        """Entities declared directly inside ``entity`` (a class's methods)."""
        ...

    def resolve_class(self, name: str, origin: CodeEntity) -> CodeEntity | None:
        """Resolve a class name as written, from ``origin``'s point of view."""
        ...

    def subclasses_of(self, entity: CodeEntity) -> Sequence[CodeEntity]:
        """Immediate subclasses declared in this project -- the input to NOC."""
        ...

    def inheritance_depth(self, entity: CodeEntity) -> int:
        """Depth of the inheritance tree, resolved within this project."""
        ...

    def referencing_classes(self, entity: CodeEntity) -> Sequence[CodeEntity]:
        """Project classes that reference ``entity`` -- the input to fan-in."""
        ...


class SmellDetector(ABC):
    """Decides whether one smell is present on an entity.

    Both the rule-based detectors (M3) and the ML-backed detectors (M5)
    implement this, which is what lets the report compare them directly.
    """

    @property
    @abstractmethod
    def smell_type(self) -> SmellType:
        """The smell this detector is responsible for."""

    @abstractmethod
    def detect(
        self, entity: CodeEntity, features: FeatureVector
    ) -> SmellPrediction | None:
        """Return a prediction, or ``None`` if the entity is out of scope."""
