"""Local feature-attribution explanations for M5 estimators.

SHAP is used when available. Logistic pipelines are explained in their scaled
feature space, where zero represents the training mean learned by
``StandardScaler``. Random forests use ``TreeExplainer``. A deterministic,
model-native fallback keeps inference usable if the optional SHAP dependency
is absent or rejects a future estimator version.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class ExplanationResult:
    method: str
    base_value: float | None
    output_value: float | None
    top_features: list[dict[str, Any]]
    warning: str | None = None


def explain_prediction(
    model: Any,
    feature_names: Sequence[str],
    values: Sequence[float],
    *,
    top_k: int = 8,
    prefer_shap: bool = True,
) -> ExplanationResult:
    return explain_predictions(
        model, feature_names, [values], top_k=top_k, prefer_shap=prefer_shap
    )[0]


def explain_predictions(
    model: Any,
    feature_names: Sequence[str],
    rows: Sequence[Sequence[float]],
    *,
    top_k: int = 8,
    prefer_shap: bool = True,
) -> list[ExplanationResult]:
    if not rows:
        return []
    if any(len(feature_names) != len(values) for values in rows):
        raise ValueError("feature names and values must have equal length")
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    matrix = np.asarray(rows, dtype=float)
    warning: str | None = None
    if prefer_shap:
        try:
            return _shap_explanations(model, feature_names, matrix, top_k)
        except Exception as exc:  # SHAP compatibility boundary
            warning = f"SHAP unavailable for this artifact: {type(exc).__name__}"
    results = _native_explanations(model, feature_names, matrix, top_k)
    return [
        ExplanationResult(
            method=result.method,
            base_value=result.base_value,
            output_value=result.output_value,
            top_features=result.top_features,
            warning=warning,
        )
        for result in results
    ]


def _shap_explanations(
    model: Any,
    feature_names: Sequence[str],
    matrix: np.ndarray,
    top_k: int,
) -> ExplanationResult:
    import shap

    if hasattr(model, "named_steps") and "scale" in model.named_steps and "classifier" in model.named_steps:
        scaler = model.named_steps["scale"]
        classifier = model.named_steps["classifier"]
        transformed = scaler.transform(matrix)
        background = np.zeros((1, transformed.shape[1]), dtype=float)
        explainer = shap.LinearExplainer(classifier, background)
        explanation = explainer(transformed)
        all_contributions = np.asarray(explanation.values)
        all_bases = np.asarray(explanation.base_values)
        results = []
        for index, contributions in enumerate(all_contributions):
            base = _row_scalar(all_bases, index)
            output = base + float(np.sum(contributions)) if base is not None else None
            results.append(
                ExplanationResult(
                    "shap_linear",
                    base,
                    output,
                    _rank(feature_names, matrix[index], contributions, top_k),
                )
            )
        return results

    explainer = shap.TreeExplainer(model, feature_perturbation="tree_path_dependent")
    explanation = explainer(matrix)
    values = np.asarray(explanation.values)
    base_values = np.asarray(explanation.base_values)
    results = []
    for index in range(matrix.shape[0]):
        if values.ndim == 3:  # samples, features, classes
            class_index = 1 if values.shape[2] > 1 else 0
            contributions = values[index, :, class_index]
            base = _row_class_scalar(base_values, index, class_index)
        elif values.ndim == 2:
            contributions = values[index]
            base = _row_scalar(base_values, index)
        else:
            raise ValueError("unsupported SHAP output shape")
        output = base + float(np.sum(contributions)) if base is not None else None
        results.append(
            ExplanationResult(
                "shap_tree",
                base,
                output,
                _rank(feature_names, matrix[index], contributions, top_k),
            )
        )
    return results


def _native_explanations(
    model: Any,
    feature_names: Sequence[str],
    matrix: np.ndarray,
    top_k: int,
) -> ExplanationResult:
    if hasattr(model, "named_steps") and "scale" in model.named_steps and "classifier" in model.named_steps:
        scaler = model.named_steps["scale"]
        classifier = model.named_steps["classifier"]
        transformed = scaler.transform(matrix)
        coefficients = np.asarray(classifier.coef_)[0]
        intercept = float(np.asarray(classifier.intercept_)[0])
        return [
            ExplanationResult(
                "linear_contribution",
                intercept,
                intercept + float(np.sum(row * coefficients)),
                _rank(feature_names, matrix[index], row * coefficients, top_k),
            )
            for index, row in enumerate(transformed)
        ]
    if hasattr(model, "feature_importances_"):
        importance = np.asarray(model.feature_importances_, dtype=float)
        return [
            ExplanationResult(
                "tree_importance_fallback",
                None,
                None,
                _rank(
                    feature_names,
                    row,
                    importance * (row - np.median(row)),
                    top_k,
                ),
            )
            for row in matrix
        ]
    return [
        ExplanationResult(
            "value_deviation_fallback",
            None,
            None,
            _rank(feature_names, row, row, top_k),
        )
        for row in matrix
    ]


def _rank(
    feature_names: Sequence[str],
    raw_values: Sequence[float],
    contributions: Sequence[float],
    top_k: int,
) -> list[dict[str, Any]]:
    ranked = sorted(
        zip(feature_names, raw_values, contributions, strict=True),
        key=lambda item: abs(float(item[2])),
        reverse=True,
    )[:top_k]
    return [
        {
            "feature": name,
            "raw_value": _finite(float(raw)),
            "contribution": _finite(float(contribution)),
            "direction": "increases_smell_risk" if contribution >= 0 else "decreases_smell_risk",
            "importance": _finite(abs(float(contribution))),
            "rank": rank,
        }
        for rank, (name, raw, contribution) in enumerate(ranked, start=1)
    ]


def _row_scalar(values: np.ndarray, row_index: int) -> float | None:
    array = np.asarray(values)
    if array.ndim == 0:
        return _finite(float(array))
    if array.ndim == 1:
        index = min(row_index, array.shape[0] - 1)
        return _finite(float(array[index]))
    return _finite(float(array[row_index].reshape(-1)[0]))


def _row_class_scalar(
    values: np.ndarray, row_index: int, class_index: int
) -> float | None:
    array = np.asarray(values)
    if array.ndim == 1:
        index = min(class_index, array.shape[0] - 1)
        return _finite(float(array[index]))
    row = array[min(row_index, array.shape[0] - 1)].reshape(-1)
    index = min(class_index, row.shape[0] - 1)
    return _finite(float(row[index]))


def _scalar(value: Any) -> float | None:
    values = np.asarray(value).reshape(-1)
    return _finite(float(values[0])) if values.size else None


def _select_class_scalar(values: np.ndarray, class_index: int) -> float | None:
    flattened = values.reshape(-1)
    if not flattened.size:
        return None
    index = min(class_index, flattened.size - 1)
    return _finite(float(flattened[index]))


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None
