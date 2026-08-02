"""M4 blinded labelling workflow."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from codesmell.cli import app
from codesmell.dataset import (
    CandidateSource,
    DatasetWriter,
    HumanLabel,
    LabelDatasetBuilder,
    SamplingConfig,
    reviewer_agreement,
    validate_review_file,
    write_final_labels,
)
from codesmell.detectors import DetectionEngine, load_rules
from codesmell.ingestion.filters import PathFilter
from codesmell.ingestion.inventory import ProjectInventoryBuilder
from codesmell.languages.python.parser import PythonParser
from codesmell.core.enums import SourceKind
from codesmell.metrics import DEFAULT_CALCULATORS
from codesmell.metrics.engine import MetricsEngine

runner = CliRunner()


def _engine() -> MetricsEngine:
    parser = PythonParser()
    return MetricsEngine(
        parsers={parser.language: parser},
        calculators=DEFAULT_CALCULATORS,
    )


def _bundle(project: Path, tmp_path: Path):
    inventory = ProjectInventoryBuilder(
        settings=_minimal_ingestion_settings(), path_filter=PathFilter()
    ).build(
        project,
        name=project.name,
        source_kind=SourceKind.DIRECTORY,
        origin=str(project),
    )
    analysis = _engine().analyze(project, inventory)
    rules = load_rules(schema=analysis.schema)
    report = DetectionEngine(rules).detect(analysis)
    config = SamplingConfig(
        negative_ratio=0.0,
        min_controls_per_smell=1,
        seed=7,
        max_snippet_lines=50,
    )
    bundle = LabelDatasetBuilder(config).build_project(analysis, report, rules)
    output = tmp_path / "dataset"
    DatasetWriter().write([bundle], output, rules, config)
    return output, bundle


def _minimal_ingestion_settings():
    from codesmell.config.settings import IngestionSettings

    return IngestionSettings()


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_builder_blinds_reviewers_from_rule_evidence(sample_project, tmp_path):
    output, bundle = _bundle(sample_project, tmp_path)
    review_header = (output / "review_tasks.csv").read_text(
        encoding="utf-8"
    ).splitlines()[0]
    evidence_header = (output / "candidate_evidence.csv").read_text(
        encoding="utf-8"
    ).splitlines()[0]

    assert bundle.tasks
    assert "rule_fired" not in review_header
    assert "conditions_json" not in review_header
    assert "rule_fired" in evidence_header
    assert "conditions_json" in evidence_header
    assert all((output / task.snippet_path).is_file() for task in bundle.tasks)


def test_controls_are_reproducible_for_same_seed(sample_project, tmp_path):
    first_output, first = _bundle(sample_project, tmp_path / "first")
    second_output, second = _bundle(sample_project, tmp_path / "second")

    assert [task.task_id for task in first.tasks] == [
        task.task_id for task in second.tasks
    ]
    assert (first_output / "review_tasks.csv").read_bytes() == (
        second_output / "review_tasks.csv"
    ).read_bytes()
    assert any(
        row.candidate_source is CandidateSource.CONTROL for row in first.evidence
    )


def test_manifest_records_research_constraints(sample_project, tmp_path):
    output, _ = _bundle(sample_project, tmp_path)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "1.0"
    constraints = manifest["research_constraints"]
    assert constraints["review_sheet_contains_metric_features"] is False
    assert constraints["training_features_must_be_recomputed_from_source"] is True


def test_validation_accepts_partial_sheet_but_complete_mode_rejects_it(
    sample_project, tmp_path
):
    output, _ = _bundle(sample_project, tmp_path)
    review = output / "review_tasks.csv"

    partial = validate_review_file(review)
    complete = validate_review_file(review, require_complete=True)

    assert partial.valid
    assert not partial.complete
    assert not complete.valid
    assert complete.unlabelled == partial.rows


def test_finalize_writes_only_human_labels_and_excludes_uncertain(
    sample_project, tmp_path
):
    output, _ = _bundle(sample_project, tmp_path)
    review = output / "review_tasks.csv"
    rows = _read(review)
    for index, row in enumerate(rows):
        row["reviewer_id"] = "reviewer-a"
        row["labelled_at"] = "2026-07-25T12:00:00Z"
        if index == 0:
            row["human_label"] = HumanLabel.PRESENT.value
            row["human_severity"] = "medium"
        elif index == 1:
            row["human_label"] = HumanLabel.UNCERTAIN.value
            row["human_severity"] = ""
        else:
            row["human_label"] = HumanLabel.ABSENT.value
            row["human_severity"] = "none"
    _write(review, rows)

    validation = validate_review_file(review, require_complete=True)
    labels_path = tmp_path / "labels.csv"
    manifest = write_final_labels(review, labels_path)
    labels = _read(labels_path)

    assert validation.valid
    assert manifest["uncertain_excluded"] == 1
    assert len(labels) == len(rows) - 1
    assert "rule_fired" not in labels[0]
    assert "conditions_json" not in labels[0]
    assert "loc" not in labels[0]
    assert {row["label"] for row in labels} <= {"0", "1"}


def test_present_label_requires_human_severity(sample_project, tmp_path):
    output, _ = _bundle(sample_project, tmp_path)
    review = output / "review_tasks.csv"
    rows = _read(review)
    rows[0]["human_label"] = HumanLabel.PRESENT.value
    rows[0]["reviewer_id"] = "reviewer-a"
    rows[0]["human_severity"] = ""
    _write(review, rows)

    report = validate_review_file(review)

    assert not report.valid
    assert any(issue.field == "human_severity" for issue in report.issues)


def test_reviewer_agreement_reports_conflicts_and_kappa(sample_project, tmp_path):
    output, _ = _bundle(sample_project, tmp_path)
    base_rows = _read(output / "review_tasks.csv")[:4]
    first_rows = []
    second_rows = []
    for index, row in enumerate(base_rows):
        left = dict(row)
        right = dict(row)
        left["reviewer_id"] = "a"
        right["reviewer_id"] = "b"
        left["human_label"] = (
            HumanLabel.PRESENT.value if index < 2 else HumanLabel.ABSENT.value
        )
        right["human_label"] = (
            HumanLabel.PRESENT.value
            if index in (0, 2)
            else HumanLabel.ABSENT.value
        )
        left["human_severity"] = "low" if left["human_label"] == "present" else "none"
        right["human_severity"] = "low" if right["human_label"] == "present" else "none"
        first_rows.append(left)
        second_rows.append(right)

    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    conflicts = tmp_path / "conflicts.csv"
    _write(first, first_rows)
    _write(second, second_rows)

    report = reviewer_agreement(first, second, conflicts_output=conflicts)

    assert report["common_tasks"] == 4
    assert report["conflicts"] == 2
    assert report["cohen_kappa"] == 0.0
    assert conflicts.is_file()


def test_dataset_cli_create_and_validate(sample_project, tmp_path, monkeypatch):
    monkeypatch.setenv("CODESMELL_WORKSPACE_ROOT", str(tmp_path / "ws"))
    from codesmell.config.settings import get_settings

    get_settings.cache_clear()
    output = tmp_path / "cli-dataset"
    created = runner.invoke(
        app,
        [
            "dataset",
            "create",
            str(sample_project),
            "--output",
            str(output),
            "--negative-ratio",
            "0",
            "--min-controls",
            "1",
        ],
    )
    validated = runner.invoke(
        app, ["dataset", "validate", str(output / "review_tasks.csv")]
    )

    assert created.exit_code == 0, created.stdout
    assert "M4 dataset created" in created.stdout
    assert validated.exit_code == 0, validated.stdout
    assert "Review validation" in validated.stdout
    get_settings.cache_clear()
