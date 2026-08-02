"""Leave-one-project-out (LOPO/LOGO) cross-project evaluation."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from statistics import mean
from typing import Any

from .evaluation import binary_metrics, probability_of_positive
from .io import MLError, PREDICTION_COLUMNS, TrainingDataset, write_csv
from .models import TrainingConfig


def leave_one_project_out(
    dataset: TrainingDataset,
    output_dir: Path,
    config: TrainingConfig,
    *,
    smell_types: tuple[str, ...] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    _prepare_dir(output_dir, overwrite)
    selected = smell_types or dataset.smells
    folds: list[dict[str, Any]] = []
    predictions: list[dict[str, object]] = []

    for smell in selected:
        if smell not in dataset.features_by_smell:
            folds.append(_skip(smell, "", "smell is absent from the dataset"))
            continue
        rows = list(dataset.rows_for(smell))
        projects = sorted({row["project_fingerprint"] for row in rows})
        if len(rows) < config.min_samples:
            folds.append(_skip(smell, "", f"fewer than {config.min_samples} rows"))
            continue
        if len(projects) < config.min_projects:
            folds.append(_skip(smell, "", f"fewer than {config.min_projects} projects"))
            continue
        feature_names = dataset.features_by_smell[smell]

        for held_out in projects:
            train_rows = [row for row in rows if row["project_fingerprint"] != held_out]
            test_rows = [row for row in rows if row["project_fingerprint"] == held_out]
            y_train = [int(row["label"]) for row in train_rows]
            y_test = [int(row["label"]) for row in test_rows]
            if len(set(y_train)) < 2:
                folds.append(
                    _skip(
                        smell,
                        held_out,
                        "training projects contain only one class",
                    )
                )
                continue
            x_train = [
                [float(row[name]) for name in feature_names]
                for row in train_rows
            ]
            x_test = [[float(row[name]) for name in feature_names] for row in test_rows]

            for kind in config.models:
                from .tuning import tune_grouped

                train_groups = [
                    row["project_fingerprint"] for row in train_rows
                ]
                estimator, tuning = tune_grouped(
                    kind,
                    x_train,
                    y_train,
                    train_groups,
                    seed=config.seed,
                    threshold=config.threshold,
                )
                probability = probability_of_positive(estimator, x_test)
                predicted = [int(value >= config.threshold) for value in probability]
                metrics = binary_metrics(y_test, predicted, probability)
                folds.append(
                    {
                        "status": "evaluated",
                        "smell_type": smell,
                        "model": kind.value,
                        "held_out_project": held_out,
                        "train_projects": len(projects) - 1,
                        "train_rows": len(train_rows),
                        "test_rows": len(test_rows),
                        "metrics": metrics,
                        "inner_grouped_tuning": tuning,
                    }
                )
                predictions.extend(
                    _prediction_rows(
                        test_rows,
                        predicted,
                        probability,
                        held_out=held_out,
                        model=kind.value,
                    )
                )

    write_csv(output_dir / "logo_predictions.csv", PREDICTION_COLUMNS, predictions)
    evaluated = [fold for fold in folds if fold["status"] == "evaluated"]
    aggregate = _aggregate(evaluated, predictions)
    report = {
        "mode": "leave_one_project_out",
        "dataset": str(dataset.path),
        "configuration": {
            "models": [kind.value for kind in config.models],
            "seed": config.seed,
            "threshold": config.threshold,
            "min_samples": config.min_samples,
            "min_projects": config.min_projects,
        },
        "evaluated_folds": len(evaluated),
        "skipped_folds": sum(fold["status"] == "skipped" for fold in folds),
        "aggregate": aggregate,
        "folds": folds,
    }
    (output_dir / "logo_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _aggregate(
    folds: list[dict[str, Any]],
    predictions: list[dict[str, object]],
) -> dict[str, Any]:
    groups = sorted(
        {(fold["smell_type"], fold["model"]) for fold in folds}
    )
    output: dict[str, Any] = {}
    for smell, model in groups:
        key = f"{smell}:{model}"
        selected_folds = [
            fold for fold in folds
            if fold["smell_type"] == smell and fold["model"] == model
        ]
        selected_predictions = [
            row for row in predictions
            if row["smell_type"] == smell and row["model"] == model
        ]
        truth = [int(row["label"]) for row in selected_predictions]
        predicted = [int(row["prediction"]) for row in selected_predictions]
        probability = [float(row["probability"]) for row in selected_predictions]
        micro = binary_metrics(truth, predicted, probability) if truth else None
        numeric_names = (
            "accuracy",
            "balanced_accuracy",
            "precision",
            "recall",
            "specificity",
            "f1",
            "mcc",
            "roc_auc",
            "pr_auc",
            "brier_score",
        )
        macro: dict[str, float | None] = {}
        for name in numeric_names:
            values = [
                fold["metrics"][name]
                for fold in selected_folds
                if fold["metrics"].get(name) is not None
            ]
            macro[name] = float(mean(values)) if values else None
        output[key] = {
            "smell_type": smell,
            "model": model,
            "folds": len(selected_folds),
            "micro": micro,
            "macro_mean": macro,
        }
    return output


def _prediction_rows(
    rows: list[Mapping[str, str]],
    prediction: list[int],
    probability: list[float],
    *,
    held_out: str,
    model: str,
) -> list[dict[str, object]]:
    output = []
    for row, predicted, score in zip(rows, prediction, probability, strict=True):
        output.append(
            {
                **{name: row.get(name, "") for name in PREDICTION_COLUMNS},
                "prediction": predicted,
                "probability": f"{score:.12g}",
                "split": "test",
                "held_out_project": held_out,
                "model": model,
            }
        )
    return output


def _skip(smell: str, project: str, reason: str) -> dict[str, str]:
    return {
        "status": "skipped",
        "smell_type": smell,
        "held_out_project": project,
        "reason": reason,
    }


def _prepare_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise MLError(
                "output directory is not empty; use --overwrite", path=str(path)
            )
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
