"""M5 project-level training and leave-one-project-out evaluation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codesmell.cli import app
from codesmell.core.enums import EntityType, SourceKind
from codesmell.dataset import LABEL_COLUMNS
from codesmell.ingestion.filters import PathFilter
from codesmell.ingestion.inventory import ProjectInventoryBuilder
from codesmell.languages.python.parser import PythonParser
from codesmell.metrics import DEFAULT_CALCULATORS
from codesmell.metrics.engine import MetricsEngine
from codesmell.ml import (
    ModelKind,
    SplitConfig,
    TrainingConfig,
    leave_one_project_out,
    load_training_dataset,
    predict_with_model,
    prepare_feature_dataset,
    project_holdout_split,
    train_holdout,
    write_split_assignments,
)
from codesmell.ml.io import MLError, TRAINING_METADATA_COLUMNS, write_csv
from codesmell.ml.models import FEATURE_PREFIX

runner = CliRunner()


def _engine() -> MetricsEngine:
    parser = PythonParser()
    return MetricsEngine(
        parsers={parser.language: parser},
        calculators=DEFAULT_CALCULATORS,
    )


def _minimal_ingestion_settings():
    from codesmell.config.settings import IngestionSettings

    return IngestionSettings()


def _analysis(project: Path):
    inventory = ProjectInventoryBuilder(
        settings=_minimal_ingestion_settings(), path_filter=PathFilter()
    ).build(
        project,
        name=project.name,
        source_kind=SourceKind.DIRECTORY,
        origin=str(project),
    )
    return _engine().analyze(project, inventory)


def _synthetic_dataset(path: Path, *, projects: int = 4, rows_per_project: int = 6):
    feature_columns = (FEATURE_PREFIX + "loc", FEATURE_PREFIX + "cyclomatic_complexity")
    rows = []
    for project_index in range(projects):
        for row_index in range(rows_per_project):
            label = (project_index + row_index) % 2
            rows.append(
                {
                    "schema_version": "2.0",
                    "task_id": f"task-{project_index}-{row_index}",
                    "project_name": f"project-{project_index}",
                    "project_fingerprint": f"fingerprint-{project_index}",
                    "source_kind": "directory",
                    "origin": f"/projects/{project_index}",
                    "source_sha256": f"sha-{project_index}-{row_index}",
                    "entity_id": f"entity-{project_index}-{row_index}",
                    "entity_type": "method",
                    "qualified_name": f"pkg.C.m{row_index}",
                    "relative_path": "pkg/service.py",
                    "start_line": str(row_index + 1),
                    "end_line": str(row_index + 2),
                    "smell_type": "long_method",
                    "label": str(label),
                    "severity": "low" if label else "none",
                    "reviewer_id": "reviewer-a",
                    "review_notes": "",
                    "labelled_at": "2026-07-25T12:00:00Z",
                    feature_columns[0]: str(8 + 25 * label + project_index),
                    feature_columns[1]: str(1 + 7 * label + row_index / 10),
                }
            )
    write_csv(path, (*TRAINING_METADATA_COLUMNS, *feature_columns), rows)
    return load_training_dataset(path)


def test_prepare_recomputes_features_and_verifies_source(sample_project, tmp_path):
    analysis = _analysis(sample_project)
    entity = next(
        item
        for item in analysis.context.entities()
        if item.entity_type is EntityType.METHOD
    )
    source = next(
        item
        for item in analysis.inventory.source_files
        if item.relative_path == entity.relative_path
    )
    labels = tmp_path / "labels.csv"
    row = {
        "task_id": "human-task-1",
        "project_name": analysis.inventory.name,
        "project_fingerprint": analysis.inventory.fingerprint,
        "source_kind": analysis.inventory.source_kind.value,
        "origin": analysis.inventory.origin,
        "source_sha256": source.sha256,
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type.value,
        "qualified_name": entity.qualified_name,
        "relative_path": entity.relative_path,
        "start_line": str(entity.start_line),
        "end_line": str(entity.end_line),
        "smell_type": "long_method",
        "label": "0",
        "severity": "none",
        "reviewer_id": "reviewer-a",
        "review_notes": "reviewed",
        "labelled_at": "2026-07-25T12:00:00Z",
    }
    write_csv(labels, LABEL_COLUMNS, [row])
    output = tmp_path / "features.csv"

    manifest = prepare_feature_dataset(labels, [analysis], output)
    dataset = load_training_dataset(output)

    assert manifest["rows"] == 1
    assert manifest["source_verification"]["source_sha256_checked"] is True
    assert dataset.rows[0]["task_id"] == "human-task-1"
    assert FEATURE_PREFIX + "loc" in dataset.features_by_smell["long_method"]


def test_prepare_rejects_changed_source_sha(sample_project, tmp_path):
    analysis = _analysis(sample_project)
    entity = next(
        item
        for item in analysis.context.entities()
        if item.entity_type is EntityType.METHOD
    )
    labels = tmp_path / "labels.csv"
    row = {
        "task_id": "human-task-1",
        "project_name": analysis.inventory.name,
        "project_fingerprint": analysis.inventory.fingerprint,
        "source_kind": analysis.inventory.source_kind.value,
        "origin": analysis.inventory.origin,
        "source_sha256": "0" * 64,
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type.value,
        "qualified_name": entity.qualified_name,
        "relative_path": entity.relative_path,
        "start_line": str(entity.start_line),
        "end_line": str(entity.end_line),
        "smell_type": "long_method",
        "label": "0",
        "severity": "none",
        "reviewer_id": "reviewer-a",
        "review_notes": "",
        "labelled_at": "",
    }
    write_csv(labels, LABEL_COLUMNS, [row])

    with pytest.raises(MLError, match="source SHA-256"):
        prepare_feature_dataset(labels, [analysis], tmp_path / "features.csv")


def test_training_dataset_rejects_smell_entity_mismatch(tmp_path):
    dataset = _synthetic_dataset(tmp_path / "dataset.csv")
    rows = [dict(row) for row in dataset.rows]
    rows[0]["entity_type"] = "class"
    broken = tmp_path / "broken.csv"
    write_csv(broken, dataset.columns, rows)

    with pytest.raises(MLError, match="mismatch"):
        load_training_dataset(broken)


def test_project_split_is_reproducible_and_group_disjoint(tmp_path):
    dataset = _synthetic_dataset(tmp_path / "dataset.csv")
    rows = dataset.rows_for("long_method")

    first = project_holdout_split(rows, SplitConfig(test_size=0.25, seed=9))
    second = project_holdout_split(rows, SplitConfig(test_size=0.25, seed=9))

    assert first == second
    assert set(first.train_projects).isdisjoint(first.test_projects)
    assert first.test_has_both_classes
    assert set(first.train_indices).isdisjoint(first.test_indices)


def test_project_split_rejects_single_project():
    rows = [
        {"project_fingerprint": "only", "label": "0"},
        {"project_fingerprint": "only", "label": "1"},
    ]
    with pytest.raises(ValueError, match="at least 2 projects"):
        project_holdout_split(rows, SplitConfig())


def test_split_assignments_never_mix_a_project(tmp_path):
    dataset = _synthetic_dataset(tmp_path / "dataset.csv")
    output = tmp_path / "split.csv"

    report = write_split_assignments(
        dataset, output, test_size=0.25, seed=3
    )
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assignments: dict[str, set[str]] = {}
    for row in rows:
        assignments.setdefault(row["project_fingerprint"], set()).add(row["split"])
    assert report["splits"][0]["status"] == "created"
    assert all(len(values) == 1 for values in assignments.values())


def test_holdout_training_saves_model_card_predictions_and_hash(tmp_path):
    dataset = _synthetic_dataset(tmp_path / "dataset.csv")
    output = tmp_path / "models"
    config = TrainingConfig(
        models=(ModelKind.LOGISTIC,),
        test_size=0.25,
        seed=4,
        min_samples=8,
    )

    report = train_holdout(dataset, output, config)
    model_dir = output / "long_method" / "logistic"
    card = json.loads((model_dir / "model_card.json").read_text(encoding="utf-8"))

    assert report["trained_models"] == 1
    assert (model_dir / "model.joblib").is_file()
    assert (output / "predictions.csv").is_file()
    assert set(card["training_projects"]).isdisjoint(card["test_projects"])
    assert card["metrics"]["support"] > 0
    assert card["inner_grouped_tuning"]["status"] == "selected"
    assert set(card["inner_grouped_tuning"]["training_projects"]).isdisjoint(
        card["test_projects"]
    )
    assert len(card["model_sha256"]) == 64


def test_saved_model_predicts_after_schema_and_hash_verification(tmp_path):
    dataset = _synthetic_dataset(tmp_path / "dataset.csv")
    output = tmp_path / "models"
    train_holdout(
        dataset,
        output,
        TrainingConfig(models=(ModelKind.LOGISTIC,), min_samples=8),
    )

    predictions = predict_with_model(
        dataset, output / "long_method" / "logistic"
    )

    assert len(predictions) == len(dataset.rows)
    assert all(0.0 <= row["probability"] <= 1.0 for row in predictions)
    assert {row["prediction"] for row in predictions} <= {0, 1}


def test_saved_model_rejects_tampering(tmp_path):
    dataset = _synthetic_dataset(tmp_path / "dataset.csv")
    output = tmp_path / "models"
    train_holdout(
        dataset,
        output,
        TrainingConfig(models=(ModelKind.LOGISTIC,), min_samples=8),
    )
    model_path = output / "long_method" / "logistic" / "model.joblib"
    model_path.write_bytes(model_path.read_bytes() + b"tampered")

    with pytest.raises(MLError, match="SHA-256"):
        predict_with_model(dataset, model_path.parent)


def test_logo_evaluates_every_project_and_aggregates(tmp_path):
    dataset = _synthetic_dataset(tmp_path / "dataset.csv", projects=4)
    output = tmp_path / "logo"
    config = TrainingConfig(
        models=(ModelKind.LOGISTIC,),
        min_samples=8,
        min_projects=2,
    )

    report = leave_one_project_out(dataset, output, config)
    aggregate = report["aggregate"]["long_method:logistic"]

    assert report["evaluated_folds"] == 4
    assert report["skipped_folds"] == 0
    assert aggregate["folds"] == 4
    assert aggregate["micro"]["support"] == 24
    assert (output / "logo_predictions.csv").is_file()
    assert (output / "logo_report.json").is_file()


def test_logo_skips_fold_whose_training_side_has_one_class(tmp_path):
    dataset = _synthetic_dataset(
        tmp_path / "dataset.csv", projects=2, rows_per_project=4
    )
    rows = [dict(row) for row in dataset.rows]
    for row in rows:
        row["label"] = "0" if row["project_fingerprint"] == "fingerprint-0" else "1"
    path = tmp_path / "single-class-fold.csv"
    write_csv(path, dataset.columns, rows)
    dataset = load_training_dataset(path)

    report = leave_one_project_out(
        dataset,
        tmp_path / "logo",
        TrainingConfig(models=(ModelKind.LOGISTIC,), min_samples=4),
    )

    assert report["evaluated_folds"] == 0
    assert report["skipped_folds"] == 2


def test_ml_cli_split_train_and_logo(tmp_path):
    _synthetic_dataset(tmp_path / "dataset.csv")
    split = runner.invoke(
        app,
        [
            "ml",
            "split",
            str(tmp_path / "dataset.csv"),
            "--output",
            str(tmp_path / "split.csv"),
            "--test-size",
            "0.25",
        ],
    )
    trained = runner.invoke(
        app,
        [
            "ml",
            "train",
            str(tmp_path / "dataset.csv"),
            "--output",
            str(tmp_path / "models"),
            "--models",
            "logistic",
            "--min-samples",
            "8",
        ],
    )
    logo = runner.invoke(
        app,
        [
            "ml",
            "logo",
            str(tmp_path / "dataset.csv"),
            "--output",
            str(tmp_path / "logo"),
            "--models",
            "logistic",
            "--min-samples",
            "8",
        ],
    )

    assert split.exit_code == 0, split.stdout
    assert trained.exit_code == 0, trained.stdout
    assert logo.exit_code == 0, logo.stdout
    assert "M5 project split" in split.stdout
    assert "Trained models" in trained.stdout
    assert "Evaluated folds" in logo.stdout
