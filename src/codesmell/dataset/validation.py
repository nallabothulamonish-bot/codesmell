"""Validation and inter-reviewer agreement for M4 label files."""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from codesmell.core.enums import Severity

from .io import REVIEW_COLUMNS, DatasetError, read_csv
from .models import HumanLabel, ReviewValidationReport, ValidationIssue


_ALLOWED_SEVERITIES = {
    Severity.LOW.value,
    Severity.MEDIUM.value,
    Severity.HIGH.value,
    Severity.CRITICAL.value,
}


def validate_review_file(
    path: Path, *, require_complete: bool = False
) -> ReviewValidationReport:
    header, rows = read_csv(path)
    issues: list[ValidationIssue] = []
    missing_columns = [column for column in REVIEW_COLUMNS if column not in header]
    for column in missing_columns:
        issues.append(ValidationIssue(1, "", column, "required column is missing"))
    if missing_columns:
        return ReviewValidationReport(0, 0, 0, 0, 0, 0, tuple(issues))

    seen: set[str] = set()
    counts: Counter[str] = Counter()
    unlabelled = 0
    for index, row in enumerate(rows, start=2):
        task_id = row.get("task_id", "").strip()
        if not task_id:
            issues.append(ValidationIssue(index, "", "task_id", "is required"))
        elif task_id in seen:
            issues.append(
                ValidationIssue(index, task_id, "task_id", "duplicate task id")
            )
        seen.add(task_id)

        for field in (
            "project_fingerprint",
            "entity_id",
            "entity_type",
            "relative_path",
            "smell_type",
            "snippet_path",
        ):
            if not row.get(field, "").strip():
                issues.append(ValidationIssue(index, task_id, field, "is required"))

        label = row.get("human_label", "").strip().lower()
        severity = row.get("human_severity", "").strip().lower()
        reviewer = row.get("reviewer_id", "").strip()

        if not label:
            unlabelled += 1
            if require_complete:
                issues.append(
                    ValidationIssue(index, task_id, "human_label", "is required")
                )
            continue
        try:
            decision = HumanLabel(label)
        except ValueError:
            issues.append(
                ValidationIssue(
                    index,
                    task_id,
                    "human_label",
                    "must be present, absent, or uncertain",
                )
            )
            continue

        counts[decision.value] += 1
        if not reviewer:
            issues.append(
                ValidationIssue(index, task_id, "reviewer_id", "is required")
            )

        if decision is HumanLabel.PRESENT:
            if severity not in _ALLOWED_SEVERITIES:
                issues.append(
                    ValidationIssue(
                        index,
                        task_id,
                        "human_severity",
                        "present labels require low, medium, high, or critical",
                    )
                )
        elif severity and severity != Severity.NONE.value:
            issues.append(
                ValidationIssue(
                    index,
                    task_id,
                    "human_severity",
                    "absent/uncertain labels must use blank or none",
                )
            )

    labelled = len(rows) - unlabelled
    return ReviewValidationReport(
        rows=len(rows),
        labelled=labelled,
        unlabelled=unlabelled,
        present=counts[HumanLabel.PRESENT.value],
        absent=counts[HumanLabel.ABSENT.value],
        uncertain=counts[HumanLabel.UNCERTAIN.value],
        issues=tuple(issues),
    )


def reviewer_agreement(
    first: Path,
    second: Path,
    *,
    conflicts_output: Path | None = None,
) -> dict[str, object]:
    """Compare two completed review sheets by stable task id.

    Cohen's kappa is calculated on common binary decisions only.  Rows marked
    uncertain are counted but excluded from kappa rather than forced into a
    nominal third category that M5 cannot train on.
    """
    first_report = validate_review_file(first, require_complete=True)
    second_report = validate_review_file(second, require_complete=True)
    if not first_report.valid or not second_report.valid:
        raise DatasetError(
            "both review files must validate before agreement is calculated",
            first_issues=len(first_report.issues),
            second_issues=len(second_report.issues),
        )

    _, first_rows = read_csv(first)
    _, second_rows = read_csv(second)
    left = {row["task_id"]: row for row in first_rows}
    right = {row["task_id"]: row for row in second_rows}
    common = sorted(left.keys() & right.keys())
    if not common:
        raise DatasetError("review files have no common task ids")

    exact = 0
    severity_exact = 0
    severity_common = 0
    binary_pairs: list[tuple[str, str]] = []
    conflicts: list[dict[str, str]] = []
    for task_id in common:
        row_a, row_b = left[task_id], right[task_id]
        label_a = row_a["human_label"].strip().lower()
        label_b = row_b["human_label"].strip().lower()
        severity_a = row_a["human_severity"].strip().lower() or "none"
        severity_b = row_b["human_severity"].strip().lower() or "none"
        if label_a == label_b:
            exact += 1
        else:
            conflicts.append(
                _conflict_row(task_id, row_a, row_b, label_a, label_b)
            )
        if label_a == label_b == HumanLabel.PRESENT.value:
            severity_common += 1
            severity_exact += severity_a == severity_b
        if (
            label_a != HumanLabel.UNCERTAIN.value
            and label_b != HumanLabel.UNCERTAIN.value
        ):
            binary_pairs.append((label_a, label_b))

    if conflicts_output is not None:
        conflicts_output.parent.mkdir(parents=True, exist_ok=True)
        columns = (
            "task_id",
            "project_name",
            "qualified_name",
            "smell_type",
            "reviewer_a",
            "label_a",
            "severity_a",
            "reviewer_b",
            "label_b",
            "severity_b",
        )
        with conflicts_output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(conflicts)

    kappa = _cohen_kappa(binary_pairs)
    return {
        "common_tasks": len(common),
        "exact_label_agreement": exact / len(common),
        "binary_tasks_for_kappa": len(binary_pairs),
        "cohen_kappa": kappa,
        "present_severity_tasks": severity_common,
        "severity_exact_agreement": (
            severity_exact / severity_common if severity_common else None
        ),
        "conflicts": len(conflicts),
        "only_in_first": len(left.keys() - right.keys()),
        "only_in_second": len(right.keys() - left.keys()),
        "conflicts_output": str(conflicts_output) if conflicts_output else None,
    }


def _cohen_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    observed = sum(left == right for left, right in pairs) / len(pairs)
    left_counts = Counter(left for left, _ in pairs)
    right_counts = Counter(right for _, right in pairs)
    expected = sum(
        (left_counts[label] / len(pairs)) * (right_counts[label] / len(pairs))
        for label in (HumanLabel.PRESENT.value, HumanLabel.ABSENT.value)
    )
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def _conflict_row(
    task_id: str,
    row_a: Mapping[str, str],
    row_b: Mapping[str, str],
    label_a: str,
    label_b: str,
) -> dict[str, str]:
    return {
        "task_id": task_id,
        "project_name": row_a.get("project_name", ""),
        "qualified_name": row_a.get("qualified_name", ""),
        "smell_type": row_a.get("smell_type", ""),
        "reviewer_a": row_a.get("reviewer_id", ""),
        "label_a": label_a,
        "severity_a": row_a.get("human_severity", ""),
        "reviewer_b": row_b.get("reviewer_id", ""),
        "label_b": label_b,
        "severity_b": row_b.get("human_severity", ""),
    }
