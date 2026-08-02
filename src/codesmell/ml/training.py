"""Leakage-safe per-smell model training and holdout evaluation."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from codesmell import __version__

from .evaluation import binary_metrics, probability_of_positive
from .io import MLError, PREDICTION_COLUMNS, TrainingDataset, write_csv
from .models import ModelKind, SplitConfig, TrainingConfig
from .splitting import project_holdout_split


def build_estimator(
    kind: ModelKind, seed: int, parameters: dict[str, Any] | None = None
) -> Any:
    parameters = parameters or {}
    if kind is ModelKind.LOGISTIC:
        return Pipeline(
            steps=[
                ("scale", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        C=float(parameters.get("c", 1.0)),
                        class_weight="balanced",
                        max_iter=3000,
                        random_state=seed,
                        solver="liblinear",
                    ),
                ),
            ]
        )
    if kind is ModelKind.RANDOM_FOREST:
        return RandomForestClassifier(
            n_estimators=int(parameters.get("n_estimators", 300)),
            max_depth=parameters.get("max_depth"),
            min_samples_leaf=int(parameters.get("min_samples_leaf", 2)),
            class_weight="balanced_subsample",
            random_state=seed,
            n_jobs=1,
        )
    raise ValueError(f"unsupported model: {kind}")


def train_holdout(
    dataset: TrainingDataset,
    output_dir: Path,
    config: TrainingConfig,
    *,
    smell_types: tuple[str, ...] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    _prepare_dir(output_dir, overwrite)
    selected = smell_types or dataset.smells
    run_results: list[dict[str, Any]] = []
    all_predictions: list[dict[str, object]] = []

    for smell in selected:
        if smell not in dataset.features_by_smell:
            run_results.append(_skip(smell, "smell is absent from the dataset"))
            continue
        rows = list(dataset.rows_for(smell))
        projects = sorted({row["project_fingerprint"] for row in rows})
        labels = {int(row["label"]) for row in rows}
        if len(rows) < config.min_samples:
            run_results.append(_skip(smell, f"fewer than {config.min_samples} rows"))
            continue
        if len(projects) < config.min_projects:
            run_results.append(
                _skip(smell, f"fewer than {config.min_projects} projects")
            )
            continue
        if len(labels) < 2:
            run_results.append(_skip(smell, "only one class is present"))
            continue

        try:
            split = project_holdout_split(
                rows, SplitConfig(test_size=config.test_size, seed=config.seed)
            )
        except ValueError as exc:
            run_results.append(_skip(smell, str(exc)))
            continue

        feature_names = dataset.features_by_smell[smell]
        train_rows = [rows[index] for index in split.train_indices]
        test_rows = [rows[index] for index in split.test_indices]
        x_train = [[float(row[name]) for name in feature_names] for row in train_rows]
        y_train = [int(row["label"]) for row in train_rows]
        x_test = [[float(row[name]) for name in feature_names] for row in test_rows]
        y_test = [int(row["label"]) for row in test_rows]

        for kind in config.models:
            from .tuning import tune_grouped

            train_groups = [row["project_fingerprint"] for row in train_rows]
            estimator, tuning = tune_grouped(
                kind,
                x_train,
                y_train,
                train_groups,
                seed=config.seed,
                threshold=config.threshold,
            )
            probability = probability_of_positive(estimator, x_test)
            prediction = [int(value >= config.threshold) for value in probability]
            metrics = binary_metrics(y_test, prediction, probability)

            model_dir = output_dir / smell / kind.value
            model_dir.mkdir(parents=True, exist_ok=True)
            model_path = model_dir / "model.joblib"
            joblib.dump(estimator, model_path)
            model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
            card = {
                "tool": {"name": "codesmell", "version": __version__},
                "task": "binary code-smell detection",
                "smell_type": smell,
                "model": kind.value,
                "threshold": config.threshold,
                "feature_names": list(feature_names),
                "feature_count": len(feature_names),
                "training_rows": len(train_rows),
                "test_rows": len(test_rows),
                "training_projects": list(split.train_projects),
                "test_projects": list(split.test_projects),
                "test_has_both_classes": split.test_has_both_classes,
                "class_balance_train": dict(Counter(y_train)),
                "class_balance_test": dict(Counter(y_test)),
                "metrics": metrics,
                "inner_grouped_tuning": tuning,
                "model_sha256": model_sha256,
                "leakage_control": (
                    "project fingerprints are disjoint across train and test"
                ),
            }
            (model_dir / "model_card.json").write_text(
                json.dumps(card, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            run_results.append({"status": "trained", **card})
            all_predictions.extend(
                _prediction_rows(
                    test_rows,
                    prediction,
                    probability,
                    split="test",
                    held_out_project="|".join(split.test_projects),
                    model=kind.value,
                )
            )

    write_csv(output_dir / "predictions.csv", PREDICTION_COLUMNS, all_predictions)
    summary = {
        "mode": "project_holdout",
        "dataset": str(dataset.path),
        "configuration": {
            "models": [kind.value for kind in config.models],
            "test_size": config.test_size,
            "seed": config.seed,
            "threshold": config.threshold,
            "min_samples": config.min_samples,
            "min_projects": config.min_projects,
        },
        "trained_models": sum(item["status"] == "trained" for item in run_results),
        "skipped": sum(item["status"] == "skipped" for item in run_results),
        "results": run_results,
    }
    (output_dir / "holdout_report.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def write_split_assignments(
    dataset: TrainingDataset,
    output_file: Path,
    *,
    test_size: float,
    seed: int,
    smell_types: tuple[str, ...] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if output_file.exists() and not overwrite:
        raise MLError(
            "output file already exists; use --overwrite", path=str(output_file)
        )
    selected = smell_types or dataset.smells
    assignments: list[dict[str, object]] = []
    summary: list[dict[str, Any]] = []
    for smell in selected:
        rows = list(dataset.rows_for(smell))
        try:
            split = project_holdout_split(
                rows, SplitConfig(test_size=test_size, seed=seed)
            )
        except ValueError as exc:
            summary.append(_skip(smell, str(exc)))
            continue
        train_indices = set(split.train_indices)
        for index, row in enumerate(rows):
            assignments.append(
                {
                    "task_id": row["task_id"],
                    "smell_type": smell,
                    "project_fingerprint": row["project_fingerprint"],
                    "split": "train" if index in train_indices else "test",
                }
            )
        summary.append(
            {
                "status": "created",
                "smell_type": smell,
                "train_projects": list(split.train_projects),
                "test_projects": list(split.test_projects),
                "train_rows": len(split.train_indices),
                "test_rows": len(split.test_indices),
                "test_has_both_classes": split.test_has_both_classes,
            }
        )
    write_csv(
        output_file,
        ("task_id", "smell_type", "project_fingerprint", "split"),
        assignments,
    )
    report = {"output": str(output_file), "splits": summary}
    output_file.with_suffix(output_file.suffix + ".json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _prediction_rows(
    rows: list[dict[str, str]] | list[Any],
    prediction: list[int],
    probability: list[float],
    *,
    split: str,
    held_out_project: str,
    model: str,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row, predicted, score in zip(rows, prediction, probability, strict=True):
        output.append(
            {
                **{name: row.get(name, "") for name in PREDICTION_COLUMNS},
                "prediction": predicted,
                "probability": f"{score:.12g}",
                "split": split,
                "held_out_project": held_out_project,
                "model": model,
            }
        )
    return output


def _skip(smell: str, reason: str) -> dict[str, str]:
    return {"status": "skipped", "smell_type": smell, "reason": reason}


def _prepare_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise MLError(
                "output directory is not empty; use --overwrite", path=str(path)
            )
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
