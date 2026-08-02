"""Domain models for the M4 human-labelling dataset layer.

The review file intentionally contains no software-metric columns and no rule
verdict.  Reviewers label source code, not the baseline detector's opinion.
Rule evidence is written to a separate audit file and features are recomputed
from source by M5, preserving training/inference parity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Mapping, Sequence

from codesmell.core.enums import Severity


DATASET_SCHEMA_VERSION = "1.0"


def utc_timestamp() -> str:
    """Return an RFC 3339 UTC timestamp without platform-dependent formatting."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class CandidateSource(StrEnum):
    """How an entity-smell pair entered the review queue."""

    RULE = "rule_candidate"
    CONTROL = "sampled_control"


class HumanLabel(StrEnum):
    """Allowed reviewer decisions.

    ``uncertain`` is deliberately retained in the review artefact but excluded
    from the final binary training labels.  Forcing ambiguity into either class
    would introduce avoidable label noise.
    """

    PRESENT = "present"
    ABSENT = "absent"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ReviewTask:
    """One blinded human judgement task."""

    task_id: str
    project_name: str
    project_fingerprint: str
    source_kind: str
    origin: str
    entity_id: str
    entity_type: str
    qualified_name: str
    relative_path: str
    start_line: int
    end_line: int
    source_sha256: str
    smell_type: str
    snippet_path: str
    human_label: str = ""
    human_severity: str = ""
    reviewer_id: str = ""
    review_notes: str = ""
    labelled_at: str = ""

    def to_row(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "project_name": self.project_name,
            "project_fingerprint": self.project_fingerprint,
            "source_kind": self.source_kind,
            "origin": self.origin,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "qualified_name": self.qualified_name,
            "relative_path": self.relative_path,
            "start_line": str(self.start_line),
            "end_line": str(self.end_line),
            "source_sha256": self.source_sha256,
            "smell_type": self.smell_type,
            "snippet_path": self.snippet_path,
            "human_label": self.human_label,
            "human_severity": self.human_severity,
            "reviewer_id": self.reviewer_id,
            "review_notes": self.review_notes,
            "labelled_at": self.labelled_at,
        }


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """Baseline evidence kept outside the blinded review sheet."""

    task_id: str
    candidate_source: CandidateSource
    rule_fired: bool
    rule_severity: Severity
    threshold_mode: str
    conditions_json: str
    rationale: str
    references_json: str

    def to_row(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "candidate_source": self.candidate_source.value,
            "rule_fired": "1" if self.rule_fired else "0",
            "rule_severity": self.rule_severity.value,
            "threshold_mode": self.threshold_mode,
            "conditions_json": self.conditions_json,
            "rationale": self.rationale,
            "references_json": self.references_json,
        }


@dataclass(frozen=True, slots=True)
class ProjectLabelBundle:
    """In-memory output for one project before files are written."""

    project: Mapping[str, object]
    tasks: Sequence[ReviewTask]
    evidence: Sequence[CandidateEvidence]
    snippets: Mapping[str, str]
    parse_failures: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DatasetBuildReport:
    """Summary returned after a dataset bundle is written."""

    output_dir: str
    projects: int
    review_tasks: int
    rule_candidates: int
    sampled_controls: int
    snippets: int
    by_smell: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "output_dir": self.output_dir,
            "projects": self.projects,
            "review_tasks": self.review_tasks,
            "rule_candidates": self.rule_candidates,
            "sampled_controls": self.sampled_controls,
            "snippets": self.snippets,
            "by_smell": dict(self.by_smell),
        }


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    row_number: int
    task_id: str
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class ReviewValidationReport:
    rows: int
    labelled: int
    unlabelled: int
    present: int
    absent: int
    uncertain: int
    issues: Sequence[ValidationIssue]

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def complete(self) -> bool:
        return self.unlabelled == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "rows": self.rows,
            "labelled": self.labelled,
            "unlabelled": self.unlabelled,
            "present": self.present,
            "absent": self.absent,
            "uncertain": self.uncertain,
            "issues": [
                {
                    "row_number": issue.row_number,
                    "task_id": issue.task_id,
                    "field": issue.field,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
            "valid": self.valid,
            "complete": self.complete,
        }
