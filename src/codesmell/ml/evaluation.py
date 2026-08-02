"""Binary evaluation metrics with honest handling of one-class folds."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
)


def binary_metrics(
    truth: Sequence[int],
    prediction: Sequence[int],
    probability: Sequence[float],
) -> dict[str, Any]:
    if not truth:
        raise ValueError("cannot evaluate an empty prediction set")
    tn, fp, fn, tp = confusion_matrix(truth, prediction, labels=[0, 1]).ravel()
    specificity = float(tn / (tn + fp)) if (tn + fp) else None
    has_both = len(set(truth)) == 2
    roc_auc = float(roc_auc_score(truth, probability)) if has_both else None
    pr_auc = float(average_precision_score(truth, probability)) if has_both else None
    balanced = (
        float(balanced_accuracy_score(truth, prediction)) if has_both else None
    )
    brier = float(brier_score_loss(truth, probability))
    metrics: dict[str, Any] = {
        "support": len(truth),
        "positives": int(sum(truth)),
        "negatives": int(len(truth) - sum(truth)),
        "positive_rate": float(sum(truth) / len(truth)),
        "predicted_positives": int(sum(prediction)),
        "accuracy": float(accuracy_score(truth, prediction)),
        "balanced_accuracy": balanced,
        "precision": float(precision_score(truth, prediction, zero_division=0)),
        "recall": float(recall_score(truth, prediction, zero_division=0)),
        "specificity": specificity,
        "f1": float(f1_score(truth, prediction, zero_division=0)),
        "mcc": float(matthews_corrcoef(truth, prediction)),
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "brier_score": brier,
        "confusion_matrix": {
            "tn": int(tn),
            "fp": int(fp),
            "fn": int(fn),
            "tp": int(tp),
        },
        "one_class_truth": not has_both,
    }
    return _finite_or_none(metrics)


def probability_of_positive(
    model: Any, matrix: Sequence[Sequence[float]]
) -> list[float]:
    if hasattr(model, "predict_proba"):
        values = model.predict_proba(matrix)
        classes = list(model.classes_)
        positive_index = classes.index(1)
        return [float(row[positive_index]) for row in values]
    scores = model.decision_function(matrix)
    return [float(1.0 / (1.0 + math.exp(-float(score)))) for score in scores]


def _finite_or_none(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _finite_or_none(item) for key, item in value.items()}
    return value
