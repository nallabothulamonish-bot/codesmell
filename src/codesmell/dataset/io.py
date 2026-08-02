"""File formats for M4 review bundles and canonical labels."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from codesmell import __version__
from codesmell.core.enums import Severity
from codesmell.core.errors import CodeSmellError
from codesmell.detectors.rules import SmellRule

from .builder import SamplingConfig
from .models import (
    DATASET_SCHEMA_VERSION,
    CandidateSource,
    DatasetBuildReport,
    HumanLabel,
    ProjectLabelBundle,
    utc_timestamp,
)


REVIEW_COLUMNS = (
    "task_id",
    "project_name",
    "project_fingerprint",
    "source_kind",
    "origin",
    "entity_id",
    "entity_type",
    "qualified_name",
    "relative_path",
    "start_line",
    "end_line",
    "source_sha256",
    "smell_type",
    "snippet_path",
    "human_label",
    "human_severity",
    "reviewer_id",
    "review_notes",
    "labelled_at",
)

EVIDENCE_COLUMNS = (
    "task_id",
    "candidate_source",
    "rule_fired",
    "rule_severity",
    "threshold_mode",
    "conditions_json",
    "rationale",
    "references_json",
)

LABEL_COLUMNS = (
    "task_id",
    "project_name",
    "project_fingerprint",
    "source_kind",
    "origin",
    "source_sha256",
    "entity_id",
    "entity_type",
    "qualified_name",
    "relative_path",
    "start_line",
    "end_line",
    "smell_type",
    "label",
    "severity",
    "reviewer_id",
    "review_notes",
    "labelled_at",
)


class DatasetError(CodeSmellError):
    code = "dataset_error"
    http_status = 400


class DatasetWriter:
    """Write one or more project bundles atomically enough for CLI use."""

    def write(
        self,
        bundles: Sequence[ProjectLabelBundle],
        output_dir: Path,
        rules: Sequence[SmellRule],
        config: SamplingConfig,
        *,
        overwrite: bool = False,
    ) -> DatasetBuildReport:
        if not bundles:
            raise DatasetError("no project bundles were supplied")
        self._prepare_output(output_dir, overwrite)
        snippets_dir = output_dir / "snippets"
        snippets_dir.mkdir(parents=True, exist_ok=True)

        tasks = [task for bundle in bundles for task in bundle.tasks]
        evidence = [row for bundle in bundles for row in bundle.evidence]
        if len(tasks) != len(evidence):
            raise DatasetError(
                "review task and evidence counts do not match",
                tasks=len(tasks),
                evidence=len(evidence),
            )

        self._write_csv(
            output_dir / "review_tasks.csv",
            REVIEW_COLUMNS,
            (task.to_row() for task in tasks),
        )
        self._write_csv(
            output_dir / "candidate_evidence.csv",
            EVIDENCE_COLUMNS,
            (row.to_row() for row in evidence),
        )

        snippets: dict[str, str] = {}
        for bundle in bundles:
            for name, source in bundle.snippets.items():
                existing = snippets.get(name)
                if existing is not None and existing != source:
                    raise DatasetError("snippet hash collision", snippet=name)
                snippets[name] = source
        for name, source in sorted(snippets.items()):
            (snippets_dir / name).write_text(source, encoding="utf-8")

        by_smell = Counter(task.smell_type for task in tasks)
        rule_candidates = sum(
            row.candidate_source is CandidateSource.RULE for row in evidence
        )
        controls = len(evidence) - rule_candidates
        manifest = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "created_at": utc_timestamp(),
            "tool": {"name": "codesmell", "version": __version__},
            "purpose": "blinded human adjudication of code-smell labels",
            "research_constraints": {
                "review_sheet_contains_metric_features": False,
                "review_sheet_contains_rule_verdict": False,
                "training_features_must_be_recomputed_from_source": True,
                "uncertain_labels_are_excluded_from_binary_training_data": True,
            },
            "ruleset_sha256": _ruleset_sha256(rules),
            "sampling": {
                "negative_ratio": config.negative_ratio,
                "min_controls_per_smell": config.min_controls_per_smell,
                "seed": config.seed,
                "max_snippet_lines": config.max_snippet_lines,
            },
            "counts": {
                "projects": len(bundles),
                "review_tasks": len(tasks),
                "rule_candidates": rule_candidates,
                "sampled_controls": controls,
                "snippets": len(snippets),
                "by_smell": dict(sorted(by_smell.items())),
            },
            "projects": [dict(bundle.project) for bundle in bundles],
            "parse_failures": {
                str(bundle.project.get("fingerprint", "")): dict(
                    bundle.parse_failures
                )
                for bundle in bundles
                if bundle.parse_failures
            },
            "files": {
                "review_tasks": "review_tasks.csv",
                "candidate_evidence": "candidate_evidence.csv",
                "labelling_guide": "LABELING_GUIDE.md",
                "snippets": "snippets/",
            },
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (output_dir / "LABELING_GUIDE.md").write_text(
            _labelling_guide(rules), encoding="utf-8"
        )

        return DatasetBuildReport(
            output_dir=str(output_dir),
            projects=len(bundles),
            review_tasks=len(tasks),
            rule_candidates=rule_candidates,
            sampled_controls=controls,
            snippets=len(snippets),
            by_smell=dict(sorted(by_smell.items())),
        )

    def _prepare_output(self, output_dir: Path, overwrite: bool) -> None:
        if output_dir.exists() and any(output_dir.iterdir()):
            if not overwrite:
                raise DatasetError(
                    "output directory is not empty; use --overwrite",
                    output_dir=str(output_dir),
                )
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_csv(
        path: Path,
        columns: Sequence[str],
        rows: Iterable[dict[str, str]],
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise DatasetError("CSV file does not exist", path=str(path))
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise DatasetError("CSV file has no header", path=str(path))
        return list(reader.fieldnames), [dict(row) for row in reader]


def write_final_labels(
    review_file: Path,
    output_file: Path,
    *,
    overwrite: bool = False,
) -> dict[str, object]:
    """Create a labels-only file; uncertain decisions are reported and omitted."""
    # Local import avoids a module cycle: validation consumes the CSV helpers
    # from this module, while finalisation must still enforce the same policy.
    from .validation import validate_review_file

    validation = validate_review_file(review_file, require_complete=True)
    if not validation.valid:
        raise DatasetError(
            "review file failed validation; run dataset validate",
            issues=len(validation.issues),
            unlabelled=validation.unlabelled,
        )
    if output_file.exists() and not overwrite:
        raise DatasetError(
            "output file already exists; use --overwrite", path=str(output_file)
        )
    _, rows = read_csv(review_file)
    labels: list[dict[str, str]] = []
    uncertain = 0
    for row in rows:
        decision = row.get("human_label", "").strip().lower()
        if decision == HumanLabel.UNCERTAIN.value:
            uncertain += 1
            continue
        if decision not in (HumanLabel.PRESENT.value, HumanLabel.ABSENT.value):
            raise DatasetError(
                "review file is incomplete or invalid; run dataset validate",
                task_id=row.get("task_id", ""),
                human_label=decision,
            )
        present = decision == HumanLabel.PRESENT.value
        severity = row.get("human_severity", "").strip().lower()
        if not present:
            severity = Severity.NONE.value
        labels.append(
            {
                "task_id": row["task_id"],
                "project_name": row["project_name"],
                "project_fingerprint": row["project_fingerprint"],
                "source_kind": row["source_kind"],
                "origin": row.get("origin", ""),
                "source_sha256": row["source_sha256"],
                "entity_id": row["entity_id"],
                "entity_type": row["entity_type"],
                "qualified_name": row["qualified_name"],
                "relative_path": row["relative_path"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "smell_type": row["smell_type"],
                "label": "1" if present else "0",
                "severity": severity,
                "reviewer_id": row["reviewer_id"],
                "review_notes": row.get("review_notes", ""),
                "labelled_at": row.get("labelled_at", ""),
            }
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    DatasetWriter._write_csv(output_file, LABEL_COLUMNS, labels)
    digest = hashlib.sha256(output_file.read_bytes()).hexdigest()
    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "created_at": utc_timestamp(),
        "source_review_file": str(review_file),
        "labels_file": str(output_file),
        "labels_sha256": digest,
        "binary_labels": len(labels),
        "uncertain_excluded": uncertain,
        "positive": sum(row["label"] == "1" for row in labels),
        "negative": sum(row["label"] == "0" for row in labels),
        "feature_policy": "recompute all features locally from verified source",
    }
    manifest_path = output_file.with_suffix(output_file.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _ruleset_sha256(rules: Sequence[SmellRule]) -> str:
    """Hash the validated rules so a dataset can reproduce candidate selection."""
    payload = "\n".join(
        repr(rule) for rule in sorted(rules, key=lambda item: item.smell_type.value)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _labelling_guide(rules: Sequence[SmellRule]) -> str:
    lines = [
        "# Code-Smell Human Labelling Guide",
        "",
        "## Blind-review protocol",
        "",
        "1. Open `review_tasks.csv` and the referenced file in `snippets/`.",
        "2. Do not open `candidate_evidence.csv` until the independent review "
        "is complete.",
        "3. Set `human_label` to `present`, `absent`, or `uncertain`.",
        "4. For `present`, set `human_severity` to `low`, `medium`, `high`, "
        "or `critical`.",
        "5. For `absent`, leave severity blank or write `none`.",
        "6. Fill `reviewer_id`; use an RFC 3339 timestamp in `labelled_at` "
        "when possible.",
        "7. Record borderline reasoning in `review_notes`.",
        "",
        "The rule detector only selected candidates. Its verdict is not ground "
        "truth, and",
        "the final training features must be recomputed from source by this project.",
        "",
        "## Smell catalogue",
        "",
    ]
    for rule in sorted(rules, key=lambda item: item.smell_type.value):
        lines.extend(
            [
                f"### `{rule.smell_type.value}` ({rule.entity_type.value})",
                "",
                rule.rationale
                or "Review whether this entity exhibits the named smell.",
                "",
            ]
        )
        if rule.references:
            lines.append("References: " + "; ".join(rule.references))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
