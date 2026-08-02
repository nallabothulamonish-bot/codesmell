"""Deterministic, auditable refactoring recommendations."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


_TEMPLATES: dict[str, tuple[str, tuple[str, ...]]] = {
    "long_method": (
        "Extract cohesive responsibilities",
        (
            "Split validation, transformation, persistence and reporting into named helper methods.",
            "Keep each extracted method focused on one outcome and pass only required data.",
            "Add characterization tests before moving code to preserve behaviour.",
        ),
    ),
    "complex_method": (
        "Reduce decision complexity",
        (
            "Replace deeply nested conditionals with guard clauses.",
            "Extract independent decision branches into clearly named methods.",
            "Consider a strategy or dispatch table when many conditions select behaviours.",
        ),
    ),
    "deep_nesting": (
        "Flatten nested control flow",
        (
            "Use early returns or continues for invalid and exceptional cases.",
            "Extract inner loops and conditions into helpers with descriptive names.",
            "Separate data preparation from decision logic.",
        ),
    ),
    "long_parameter_list": (
        "Clarify the method interface",
        (
            "Group related parameters into a validated parameter object.",
            "Remove parameters that can be derived or obtained from the owning object.",
            "Split commands that perform unrelated operations.",
        ),
    ),
    "god_class": (
        "Decompose the oversized class",
        (
            "Identify clusters of methods and fields that change together.",
            "Extract those clusters into domain services or value objects.",
            "Retain a small coordinating façade only when callers need one entry point.",
        ),
    ),
    "large_class": (
        "Separate class responsibilities",
        (
            "Group related methods and state by responsibility.",
            "Extract stable collaborators behind narrow interfaces.",
            "Move utility behaviour that does not use instance state out of the class.",
        ),
    ),
    "feature_envy": (
        "Move behaviour closer to its data",
        (
            "Move the method, or a cohesive part of it, to the object whose data it uses most.",
            "Expose an intention-revealing operation instead of repeatedly reading foreign fields.",
            "Avoid broad getters that increase coupling.",
        ),
    ),
    "data_class": (
        "Restore domain behaviour",
        (
            "Move validation and invariant-preserving operations beside the data.",
            "Restrict direct mutation and expose meaningful domain methods.",
            "Keep it as a data transfer object only when that role is deliberate.",
        ),
    ),
    "brain_method": (
        "Break the brain method into stages",
        (
            "Name and extract the major algorithmic phases.",
            "Replace temporary-variable chains with small value objects where useful.",
            "Isolate branching policies from orchestration.",
        ),
    ),
    "brain_class": (
        "Distribute concentrated intelligence",
        (
            "Extract behaviour and state that form independent concepts.",
            "Introduce collaborators for policy, persistence and transformation concerns.",
            "Reduce the class to coordination and domain-level decisions.",
        ),
    ),
}


def build_recommendation(
    smell_type: str,
    metrics: Mapping[str, float],
    top_features: Sequence[Mapping[str, Any]],
    *,
    probability: float,
) -> dict[str, Any]:
    title, actions = _TEMPLATES.get(
        smell_type,
        (
            "Review the concentrated responsibility",
            (
                "Inspect the highest-contributing metrics and identify the responsibility they represent.",
                "Refactor in small behaviour-preserving steps with tests.",
                "Re-run analysis after each change and compare the metric trend.",
            ),
        ),
    )
    evidence = []
    for feature in top_features[:5]:
        name = str(feature.get("feature", "")).removeprefix("feature__")
        raw = feature.get("raw_value", metrics.get(name))
        evidence.append(
            {
                "metric": name,
                "value": raw,
                "direction": feature.get("direction"),
                "contribution": feature.get("contribution"),
            }
        )
    priority = "high" if probability >= 0.85 else "medium" if probability >= 0.65 else "low"
    return {
        "title": title,
        "summary": (
            f"The {smell_type.replace('_', ' ')} model estimated a "
            f"{probability:.1%} probability. Apply the changes incrementally "
            "and verify behaviour with tests."
        ),
        "priority": priority,
        "actions": list(actions),
        "evidence": evidence,
        "validation_steps": [
            "Run the existing automated tests before and after refactoring.",
            "Re-run CodeSmell and confirm the probability and contributing metrics decrease.",
            "Review readability and responsibility boundaries; do not optimize metrics alone.",
        ],
    }
