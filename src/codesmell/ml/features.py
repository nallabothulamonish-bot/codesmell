"""Recompute M2 metrics from verified source and join them to M4 labels."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from codesmell import __version__
from codesmell.core.enums import EntityType, SmellType
from codesmell.dataset import LABEL_COLUMNS, read_csv
from codesmell.metrics.engine import AnalysisResult

from .io import MLError, TRAINING_METADATA_COLUMNS, write_csv
from .models import FEATURE_PREFIX, ML_DATASET_SCHEMA_VERSION


def prepare_feature_dataset(
    labels_file: Path,
    analyses: Sequence[AnalysisResult],
    output_file: Path,
    *,
    overwrite: bool = False,
) -> dict[str, object]:
    """Join canonical human labels to freshly recomputed feature vectors.

    Project fingerprints and per-file SHA-256 values are checked before any row
    is emitted. This prevents a reviewer label from silently attaching to a
    changed entity or a different checkout.
    """
    if output_file.exists() and not overwrite:
        raise MLError(
            "output file already exists; use --overwrite", path=str(output_file)
        )
    columns, labels = read_csv(labels_file)
    missing = [name for name in LABEL_COLUMNS if name not in columns]
    if missing:
        raise MLError("labels file is missing required columns", missing=missing)
    if not labels:
        raise MLError("labels file contains no binary labels")

    by_fingerprint: dict[str, AnalysisResult] = {}
    for analysis in analyses:
        fingerprint = analysis.inventory.fingerprint
        if fingerprint in by_fingerprint:
            raise MLError(
                "duplicate project fingerprint supplied",
                project_fingerprint=fingerprint,
            )
        by_fingerprint[fingerprint] = analysis

    required_fingerprints = {row["project_fingerprint"] for row in labels}
    missing_projects = sorted(required_fingerprints - set(by_fingerprint))
    extra_projects = sorted(set(by_fingerprint) - required_fingerprints)
    if missing_projects:
        raise MLError(
            "source projects do not cover every label fingerprint",
            missing_fingerprints=missing_projects,
        )

    feature_names = sorted(
        {
            name
            for analysis in analyses
            for entity_type in EntityType
            for name in analysis.schema.names_for(entity_type)
        }
    )
    feature_columns = tuple(FEATURE_PREFIX + name for name in feature_names)
    rows: list[dict[str, object]] = []
    counts = Counter()

    for label in labels:
        analysis = by_fingerprint[label["project_fingerprint"]]
        entity = analysis.context.entity_by_id(label["entity_id"])
        if entity is None:
            raise MLError(
                "labelled entity was not found in verified source",
                task_id=label["task_id"],
                entity_id=label["entity_id"],
            )
        vector = analysis.features.get(entity.entity_id)
        if vector is None:
            raise MLError(
                "labelled entity has no feature vector",
                task_id=label["task_id"],
                entity_id=entity.entity_id,
            )
        try:
            smell = SmellType(label["smell_type"])
        except ValueError as exc:
            raise MLError(
                "unknown smell type in labels",
                task_id=label["task_id"],
                smell_type=label["smell_type"],
            ) from exc
        if smell.entity_type is not entity.entity_type:
            raise MLError(
                "labelled smell does not match entity type",
                task_id=label["task_id"],
                smell_type=smell.value,
                entity_type=entity.entity_type.value,
            )

        source_files = {
            source.relative_path: source
            for source in analysis.inventory.source_files
        }
        source = source_files.get(entity.relative_path)
        if source is None or source.sha256 != label["source_sha256"]:
            raise MLError(
                "source SHA-256 does not match the reviewed snapshot",
                task_id=label["task_id"],
                relative_path=entity.relative_path,
                expected=label["source_sha256"],
                actual=source.sha256 if source else "missing",
            )
        if (
            entity.relative_path != label["relative_path"]
            or entity.qualified_name != label["qualified_name"]
            or entity.entity_type.value != label["entity_type"]
        ):
            raise MLError(
                "label metadata does not match recomputed entity",
                task_id=label["task_id"],
            )

        applicable = analysis.schema.names_for(entity.entity_type)
        row: dict[str, object] = {
            "schema_version": ML_DATASET_SCHEMA_VERSION,
            **{name: label.get(name, "") for name in TRAINING_METADATA_COLUMNS[1:]},
        }
        for name in applicable:
            row[FEATURE_PREFIX + name] = vector.values[name]
        rows.append(row)
        counts[smell.value] += 1

    all_columns = (*TRAINING_METADATA_COLUMNS, *feature_columns)
    write_csv(output_file, all_columns, rows)
    digest = hashlib.sha256(output_file.read_bytes()).hexdigest()
    schema_payload = {
        entity_type.value: [
            FEATURE_PREFIX + name
            for name in analyses[0].schema.names_for(entity_type)
        ]
        for entity_type in EntityType
    } if analyses else {}
    manifest = {
        "schema_version": ML_DATASET_SCHEMA_VERSION,
        "created_by": {"name": "codesmell", "version": __version__},
        "labels_file": str(labels_file),
        "training_file": str(output_file),
        "training_sha256": digest,
        "rows": len(rows),
        "projects": len(required_fingerprints),
        "by_smell": dict(sorted(counts.items())),
        "feature_schema": schema_payload,
        "source_verification": {
            "project_fingerprints_checked": True,
            "source_sha256_checked": True,
            "entity_metadata_checked": True,
            "extra_sources_ignored": extra_projects,
        },
    }
    manifest_path = output_file.with_suffix(output_file.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
