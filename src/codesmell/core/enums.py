"""Domain enumerations.

This module is the shared vocabulary of the whole system. It has no
dependencies of any kind (not even on other modules in this package) so that
every layer can import it without creating a cycle.
"""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    """A programming language the analysis engine can recognise."""

    PYTHON = "python"
    JAVA = "java"
    UNKNOWN = "unknown"

    @property
    def is_supported(self) -> bool:
        """Whether a parser adapter exists for this language."""
        return self in _SUPPORTED_LANGUAGES

    @classmethod
    def supported(cls) -> frozenset[Language]:
        return _SUPPORTED_LANGUAGES


#: Languages with a registered parser adapter. Java moves in here at M2b.
_SUPPORTED_LANGUAGES: frozenset[Language] = frozenset({Language.PYTHON})


class BuildTool(StrEnum):
    """A dependency/build manager detected from marker files."""

    PIP = "pip"
    POETRY = "poetry"
    PIPENV = "pipenv"
    SETUPTOOLS = "setuptools"
    PDM = "pdm"
    HATCH = "hatch"
    CONDA = "conda"
    MAVEN = "maven"
    GRADLE = "gradle"
    UNKNOWN = "unknown"


class SourceKind(StrEnum):
    """How a project was handed to the platform."""

    DIRECTORY = "directory"
    ARCHIVE = "archive"
    SINGLE_FILE = "single_file"
    GIT = "git"


class EntityType(StrEnum):
    """The unit of analysis a metric or prediction attaches to.

    Class-level and method-level entities have disjoint feature spaces and are
    modelled separately (see the architecture roadmap, section 1.1). This enum
    is therefore a first-class key in the feature registry, the model registry
    and the database schema -- never an afterthought.
    """

    MODULE = "module"
    CLASS = "class"
    METHOD = "method"
    FUNCTION = "function"

    @property
    def is_callable(self) -> bool:
        return self in (EntityType.METHOD, EntityType.FUNCTION)


class Severity(StrEnum):
    """Ordinal severity of a detected smell.

    Ordering matters: severity is predicted by an ordinal second-stage model,
    so the numeric rank must be stable and explicit.
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANKS[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank


_SEVERITY_RANKS: dict[Severity, int] = {
    Severity.NONE: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class SmellType(StrEnum):
    """Catalogue of detectable smells, tagged with their unit of analysis."""

    # Class-level
    GOD_CLASS = "god_class"
    LARGE_CLASS = "large_class"
    DATA_CLASS = "data_class"
    LAZY_CLASS = "lazy_class"
    REFUSED_BEQUEST = "refused_bequest"
    BRAIN_CLASS = "brain_class"
    SHOTGUN_SURGERY = "shotgun_surgery"
    DIVERGENT_CHANGE = "divergent_change"
    INAPPROPRIATE_INTIMACY = "inappropriate_intimacy"
    MIDDLE_MAN = "middle_man"
    SPECULATIVE_GENERALITY = "speculative_generality"

    # Method-level
    LONG_METHOD = "long_method"
    BRAIN_METHOD = "brain_method"
    FEATURE_ENVY = "feature_envy"
    LONG_PARAMETER_LIST = "long_parameter_list"
    DEEP_NESTING = "deep_nesting"
    COMPLEX_METHOD = "complex_method"
    MESSAGE_CHAIN = "message_chain"
    MAGIC_NUMBER = "magic_number"
    DEAD_CODE = "dead_code"
    DUPLICATE_CODE = "duplicate_code"

    @property
    def entity_type(self) -> EntityType:
        return _SMELL_ENTITY_TYPES[self]


_SMELL_ENTITY_TYPES: dict[SmellType, EntityType] = {
    SmellType.GOD_CLASS: EntityType.CLASS,
    SmellType.LARGE_CLASS: EntityType.CLASS,
    SmellType.DATA_CLASS: EntityType.CLASS,
    SmellType.LAZY_CLASS: EntityType.CLASS,
    SmellType.REFUSED_BEQUEST: EntityType.CLASS,
    SmellType.BRAIN_CLASS: EntityType.CLASS,
    SmellType.SHOTGUN_SURGERY: EntityType.CLASS,
    SmellType.DIVERGENT_CHANGE: EntityType.CLASS,
    SmellType.INAPPROPRIATE_INTIMACY: EntityType.CLASS,
    SmellType.MIDDLE_MAN: EntityType.CLASS,
    SmellType.SPECULATIVE_GENERALITY: EntityType.CLASS,
    SmellType.LONG_METHOD: EntityType.METHOD,
    SmellType.BRAIN_METHOD: EntityType.METHOD,
    SmellType.FEATURE_ENVY: EntityType.METHOD,
    SmellType.LONG_PARAMETER_LIST: EntityType.METHOD,
    SmellType.DEEP_NESTING: EntityType.METHOD,
    SmellType.COMPLEX_METHOD: EntityType.METHOD,
    SmellType.MESSAGE_CHAIN: EntityType.METHOD,
    SmellType.MAGIC_NUMBER: EntityType.METHOD,
    SmellType.DEAD_CODE: EntityType.METHOD,
    SmellType.DUPLICATE_CODE: EntityType.METHOD,
}


class JobStatus(StrEnum):
    """Lifecycle of an asynchronous analysis job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )


class RejectionReason(StrEnum):
    """Why an archive member or repository file was refused.

    Every rejection is surfaced to the user rather than silently dropped, so
    the reason has to be a stable machine-readable value.
    """

    PATH_TRAVERSAL = "path_traversal"
    ABSOLUTE_PATH = "absolute_path"
    SYMLINK = "symlink"
    SPECIAL_FILE = "special_file"
    MEMBER_LIMIT = "member_limit"
    MEMBER_TOO_LARGE = "member_too_large"
    TOTAL_SIZE_LIMIT = "total_size_limit"
    COMPRESSION_RATIO = "compression_ratio"
    DISALLOWED_SUFFIX = "disallowed_suffix"
    EXCLUDED_PATH = "excluded_path"
    BINARY_CONTENT = "binary_content"
    UNDECODABLE = "undecodable"
