"""Trusted server-side registry for M5 model artifacts.

``joblib`` uses Python pickle internally and must never be loaded from an
untrusted HTTP upload. Registration is therefore an administrator operation:
the CLI verifies the model card and SHA-256, copies the two files into private
storage, and records immutable metadata in the database.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from codesmell.core.enums import SmellType
from codesmell.db.models import ModelArtifact
from codesmell.ml.models import FEATURE_PREFIX, ModelKind


class ModelRegistryError(ValueError):
    """A model artifact failed structural or integrity validation."""


@dataclass(frozen=True, slots=True)
class ModelArtifactData:
    model_path: Path
    card_path: Path
    card: dict[str, Any]
    sha256: str


class ModelRegistry:
    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root.resolve() / "models"
        self.root.mkdir(parents=True, exist_ok=True)

    def validate_directory(self, model_dir: Path) -> ModelArtifactData:
        directory = model_dir.expanduser().resolve()
        model_path = directory / "model.joblib"
        card_path = directory / "model_card.json"
        if not model_path.is_file() or not card_path.is_file():
            raise ModelRegistryError(
                "model directory must contain model.joblib and model_card.json"
            )
        try:
            card = json.loads(card_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelRegistryError("model_card.json is not valid JSON") from exc
        if not isinstance(card, dict):
            raise ModelRegistryError("model card must be a JSON object")

        required = {"smell_type", "model", "threshold", "feature_names", "model_sha256"}
        missing = sorted(required - set(card))
        if missing:
            raise ModelRegistryError(f"model card is missing: {', '.join(missing)}")
        try:
            smell = SmellType(str(card["smell_type"]))
        except ValueError as exc:
            raise ModelRegistryError("model card has an unknown smell_type") from exc
        try:
            ModelKind(str(card["model"]))
        except ValueError as exc:
            raise ModelRegistryError("model card has an unsupported model kind") from exc
        features = card["feature_names"]
        if not isinstance(features, list) or not features:
            raise ModelRegistryError("feature_names must be a non-empty list")
        if any(not isinstance(name, str) or not name.startswith(FEATURE_PREFIX) for name in features):
            raise ModelRegistryError("every feature name must use the feature__ prefix")
        if len(features) != len(set(features)):
            raise ModelRegistryError("feature_names contains duplicates")
        threshold = float(card["threshold"])
        if not 0.0 < threshold < 1.0:
            raise ModelRegistryError("model threshold must be between 0 and 1")
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if digest != str(card["model_sha256"]):
            raise ModelRegistryError("model SHA-256 does not match model card")
        # Materialize enum validation without changing the original card.
        _ = smell.entity_type
        return ModelArtifactData(model_path, card_path, card, digest)

    def register(
        self,
        session: Session,
        model_dir: Path,
        *,
        name: str | None = None,
        enabled: bool = True,
    ) -> ModelArtifact:
        data = self.validate_directory(model_dir)
        duplicate = session.scalar(
            select(ModelArtifact).where(ModelArtifact.model_sha256 == data.sha256)
        )
        if duplicate is not None:
            self.verify(duplicate)
            if name:
                duplicate.name = name.strip()[:160] or duplicate.name
            duplicate.enabled = enabled
            session.commit()
            session.refresh(duplicate)
            return duplicate

        artifact_id = str(uuid.uuid4())
        destination = self.root / artifact_id
        destination.mkdir(parents=True, exist_ok=False)
        destination.chmod(0o700)
        stored_model = destination / "model.joblib"
        stored_card = destination / "model_card.json"
        shutil.copy2(data.model_path, stored_model)
        shutil.copy2(data.card_path, stored_card)
        stored_model.chmod(0o600)
        stored_card.chmod(0o600)
        card = dict(data.card)
        artifact = ModelArtifact(
            id=artifact_id,
            name=(name or f"{card['smell_type']} {card['model']}").strip()[:160],
            smell_type=str(card["smell_type"]),
            entity_type=SmellType(str(card["smell_type"])).entity_type.value,
            model_kind=str(card["model"]),
            artifact_path=str(destination),
            model_sha256=data.sha256,
            threshold=float(card["threshold"]),
            feature_names=list(card["feature_names"]),
            model_card=card,
            enabled=enabled,
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        return artifact

    def verify(self, artifact: ModelArtifact) -> ModelArtifactData:
        data = self.validate_directory(Path(artifact.artifact_path))
        if data.sha256 != artifact.model_sha256:
            raise ModelRegistryError("registered model hash no longer matches database")
        if data.card["smell_type"] != artifact.smell_type:
            raise ModelRegistryError("registered smell type no longer matches model card")
        if list(data.card["feature_names"]) != list(artifact.feature_names):
            raise ModelRegistryError("registered feature schema no longer matches model card")
        return data

    def delete_files(self, artifact: ModelArtifact) -> None:
        path = Path(artifact.artifact_path).resolve()
        if path.parent == self.root and path.is_dir():
            shutil.rmtree(path)
