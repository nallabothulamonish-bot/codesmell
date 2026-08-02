"""Grouped inner cross-validation for leakage-free hyperparameter selection."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from sklearn.model_selection import GroupKFold

from .evaluation import binary_metrics, probability_of_positive
from .models import ModelKind


def candidate_parameters(kind: ModelKind) -> tuple[dict[str, Any], ...]:
    """Small CPU-friendly grids suitable for nested cross-project evaluation."""
    if kind is ModelKind.LOGISTIC:
        return (
            {"c": 0.1},
            {"c": 1.0},
            {"c": 10.0},
        )
    if kind is ModelKind.RANDOM_FOREST:
        return (
            {"n_estimators": 200, "max_depth": None, "min_samples_leaf": 1},
            {"n_estimators": 200, "max_depth": None, "min_samples_leaf": 2},
            {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 1},
            {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 2},
        )
    raise ValueError(f"unsupported model: {kind}")


def tune_grouped(
    kind: ModelKind,
    matrix: Sequence[Sequence[float]],
    labels: Sequence[int],
    groups: Sequence[str],
    *,
    seed: int,
    threshold: float,
) -> tuple[Any, dict[str, Any]]:
    """Select hyperparameters using only group-isolated inner folds.

    The returned estimator is fitted on the complete outer-training partition.
    If grouped tuning is impossible, a documented default is fitted instead.
    """
    from .training import build_estimator

    unique_groups = sorted(set(groups))
    candidates = candidate_parameters(kind)
    if len(unique_groups) < 2:
        params = candidates[0]
        estimator = build_estimator(kind, seed, params)
        estimator.fit(matrix, labels)
        return estimator, {
            "status": "skipped",
            "reason": "fewer than 2 training projects",
            "training_projects": unique_groups,
            "selected_parameters": params,
            "candidates": [],
        }

    n_splits = min(3, len(unique_groups))
    splitter = GroupKFold(n_splits=n_splits)
    results: list[dict[str, Any]] = []
    best: tuple[tuple[float, float, float], dict[str, Any]] | None = None

    for candidate_index, params in enumerate(candidates):
        truth: list[int] = []
        predicted: list[int] = []
        probability: list[float] = []
        valid_folds = 0
        skipped_folds = 0
        for train_index, validation_index in splitter.split(matrix, labels, groups):
            y_train = [labels[index] for index in train_index]
            if len(set(y_train)) < 2:
                skipped_folds += 1
                continue
            estimator = build_estimator(kind, seed + candidate_index, params)
            x_train = [matrix[index] for index in train_index]
            x_validation = [matrix[index] for index in validation_index]
            y_validation = [labels[index] for index in validation_index]
            estimator.fit(x_train, y_train)
            scores = probability_of_positive(estimator, x_validation)
            decisions = [int(score >= threshold) for score in scores]
            truth.extend(y_validation)
            probability.extend(scores)
            predicted.extend(decisions)
            valid_folds += 1

        if not truth:
            results.append(
                {
                    "parameters": params,
                    "status": "invalid",
                    "valid_folds": valid_folds,
                    "skipped_folds": skipped_folds,
                    "reason": "no inner fold had both classes in training",
                }
            )
            continue
        metrics = binary_metrics(truth, predicted, probability)
        score = (
            float(metrics["mcc"] or 0.0),
            float(metrics["f1"] or 0.0),
            float(metrics["pr_auc"] or 0.0),
        )
        result = {
            "parameters": params,
            "status": "evaluated",
            "valid_folds": valid_folds,
            "skipped_folds": skipped_folds,
            "metrics": metrics,
            "selection_score": list(score),
        }
        results.append(result)
        if best is None or score > best[0]:
            best = (score, params)

    selected = best[1] if best is not None else candidates[0]
    estimator = build_estimator(kind, seed, selected)
    estimator.fit(matrix, labels)
    return estimator, {
        "status": "selected" if best is not None else "fallback",
        "selection_metric_order": ["mcc", "f1", "pr_auc"],
        "inner_splits": n_splits,
        "training_projects": unique_groups,
        "class_balance": dict(Counter(labels)),
        "selected_parameters": selected,
        "candidates": results,
    }
