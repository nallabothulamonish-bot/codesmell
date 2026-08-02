"""CSV schema validation and serialization for M5 feature datasets."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from codesmell.core.enums import EntityType, SmellType
from codesmell.core.errors import CodeSmellError

from .models import FEATURE_PREFIX

TRAINING_METADATA_COLUMNS = (
    "schema_version",
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

PREDICTION_COLUMNS = (
    "task_id",
    "project_name",
    "project_fingerprint",
    "entity_id",
    "entity_type",
    "qualified_name",
    "relative_path",
    "start_line",
    "smell_type",
    "label",
    "prediction",
    "probability",
    "split",
    "held_out_project",
    "model",
)


class MLError(CodeSmellError):
    code = "ml_error"
    http_status = 400


@dataclass(frozen=True, slots=True)
class TrainingDataset:
    """Validated rows plus stable feature spaces for every smell."""

    path: Path
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, str], ...]
    features_by_smell: Mapping[str, tuple[str, ...]]

    @property
    def smells(self) -> tuple[str, ...]:
        return tuple(sorted(self.features_by_smell))

    def rows_for(self, smell_type: str) -> tuple[Mapping[str, str], ...]:
        return tuple(row for row in self.rows if row["smell_type"] == smell_type)

    def matrix_for(
        self, smell_type: str, rows: Sequence[Mapping[str, str]] | None = None
    ) -> tuple[list[list[float]], list[int], list[str]]:
        selected = tuple(rows) if rows is not None else self.rows_for(smell_type)
        features = self.features_by_smell[smell_type]
        matrix = [
            [float(row[name]) for name in features]
            for row in selected
        ]
        labels = [int(row["label"]) for row in selected]
        groups = [row["project_fingerprint"] for row in selected]
        return matrix, labels, groups


def load_training_dataset(path: Path) -> TrainingDataset:
    """Read and strictly validate an M5 feature CSV."""
    if not path.is_file():
        raise MLError("training dataset does not exist", path=str(path))
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise MLError("training dataset has no header", path=str(path))
        columns = tuple(reader.fieldnames)
        rows = tuple(dict(row) for row in reader)

    missing = [name for name in TRAINING_METADATA_COLUMNS if name not in columns]
    if missing:
        raise MLError("training dataset is missing required columns", missing=missing)
    feature_columns = tuple(name for name in columns if name.startswith(FEATURE_PREFIX))
    if not feature_columns:
        raise MLError("training dataset contains no feature columns")
    if not rows:
        raise MLError("training dataset contains no rows")

    seen_tasks: set[str] = set()
    by_smell_features: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for index, row in enumerate(rows, start=2):
        task_id = row.get("task_id", "").strip()
        if not task_id:
            raise MLError("blank task_id", row=index)
        if task_id in seen_tasks:
            raise MLError("duplicate task_id", row=index, task_id=task_id)
        seen_tasks.add(task_id)

        try:
            smell = SmellType(row["smell_type"].strip())
            entity_type = EntityType(row["entity_type"].strip())
        except ValueError as exc:
            raise MLError("invalid smell or entity type", row=index) from exc
        if smell.entity_type is not entity_type:
            raise MLError(
                "smell/entity type mismatch",
                row=index,
                smell_type=smell.value,
                entity_type=entity_type.value,
            )
        if row["label"].strip() not in {"0", "1"}:
            raise MLError("label must be 0 or 1", row=index, task_id=task_id)
        if not row["project_fingerprint"].strip():
            raise MLError("project_fingerprint is required", row=index)

        populated: list[str] = []
        for name in feature_columns:
            raw = row.get(name, "").strip()
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError as exc:
                raise MLError(
                    "feature is not numeric", row=index, feature=name, value=raw
                ) from exc
            if not math.isfinite(value):
                raise MLError(
                    "feature is not finite", row=index, feature=name, value=raw
                )
            populated.append(name)
        if not populated:
            raise MLError("row contains no applicable features", row=index)
        by_smell_features[smell.value].add(tuple(populated))

    normalized: dict[str, tuple[str, ...]] = {}
    for smell, schemas in by_smell_features.items():
        if len(schemas) != 1:
            raise MLError(
                "inconsistent feature columns within smell",
                smell_type=smell,
                schemas=[list(item) for item in sorted(schemas)],
            )
        normalized[smell] = next(iter(schemas))

    return TrainingDataset(
        path=path,
        columns=columns,
        rows=rows,
        features_by_smell=normalized,
    )


def write_csv(
    path: Path,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
