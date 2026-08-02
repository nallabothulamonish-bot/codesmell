"""M7 model registry, local explanations and refactoring advice."""

from codesmell.explain.explanations import (
    ExplanationResult,
    explain_prediction,
    explain_predictions,
)
from codesmell.explain.recommendations import build_recommendation
from codesmell.explain.registry import ModelArtifactData, ModelRegistry

__all__ = [
    "ExplanationResult",
    "ModelArtifactData",
    "ModelRegistry",
    "build_recommendation",
    "explain_prediction",
    "explain_predictions",
]
