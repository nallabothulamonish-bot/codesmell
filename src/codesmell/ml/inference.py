"""Load an M5 model artifact and predict rows with schema verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import joblib

from .evaluation import probability_of_positive
from .io import MLError, TrainingDataset


def predict_with_model(
    dataset: TrainingDataset,
    model_dir: Path,
    *,
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    card_path = model_dir / "model_card.json"
    model_path = model_dir / "model.joblib"
    if not card_path.is_file() or not model_path.is_file():
        raise MLError("model directory is missing model.joblib or model_card.json")
    card = json.loads(card_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if digest != card.get("model_sha256"):
        raise MLError("model SHA-256 does not match model card")
    smell = str(card["smell_type"])
    expected = tuple(card["feature_names"])
    actual = dataset.features_by_smell.get(smell)
    if actual != expected:
        raise MLError(
            "feature schema does not match model",
            smell_type=smell,
            expected=list(expected),
            actual=list(actual or ()),
        )
    rows = list(dataset.rows_for(smell))
    matrix = [[float(row[name]) for name in expected] for row in rows]
    model = joblib.load(model_path)
    probability = probability_of_positive(model, matrix)
    cutoff = float(card["threshold"] if threshold is None else threshold)
    return [
        {
            "task_id": row["task_id"],
            "project_fingerprint": row["project_fingerprint"],
            "entity_id": row["entity_id"],
            "smell_type": smell,
            "prediction": int(score >= cutoff),
            "probability": score,
            "model": card["model"],
        }
        for row, score in zip(rows, probability, strict=True)
    ]
