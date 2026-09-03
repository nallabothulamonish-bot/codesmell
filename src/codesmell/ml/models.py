"""Domain models and configuration for M5 machine learning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

ML_DATASET_SCHEMA_VERSION = "2.0"
FEATURE_PREFIX = "feature__"


class ModelKind(StrEnum):
    """Supported, CPU-friendly binary classifiers."""

    LOGISTIC = "logistic"
    RANDOM_FOREST = "random_forest"
    GRADIENT_BOOSTING = "gradient_boosting"
    DECISION_TREE = "decision_tree"


@dataclass(frozen=True, slots=True)
class SplitConfig:
    """Leakage-safe project-level holdout settings."""

    test_size: float = 0.2
    seed: int = 42
    max_attempts: int = 256

    def __post_init__(self) -> None:
        if not 0.0 < self.test_size < 1.0:
            raise ValueError("test_size must be between 0 and 1")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """Shared training and evaluation settings."""

    models: tuple[ModelKind, ...] = (
        ModelKind.LOGISTIC,
        ModelKind.RANDOM_FOREST,
    )
    test_size: float = 0.2
    seed: int = 42
    threshold: float = 0.5
    min_samples: int = 10
    min_projects: int = 2

    def __post_init__(self) -> None:
        if not self.models:
            raise ValueError("at least one model is required")
        if not 0.0 < self.test_size < 1.0:
            raise ValueError("test_size must be between 0 and 1")
        if not 0.0 < self.threshold < 1.0:
            raise ValueError("threshold must be between 0 and 1")
        if self.min_samples < 2:
            raise ValueError("min_samples must be at least 2")
        if self.min_projects < 2:
            raise ValueError("min_projects must be at least 2")
