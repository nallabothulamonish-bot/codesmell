from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import joblib
import pytest
from fastapi.testclient import TestClient

from codesmell.api.app import create_app
from codesmell.config.settings import Settings
from codesmell.db.models import ModelArtifact
from codesmell.explain import ModelRegistry, explain_prediction, explain_predictions
from codesmell.jobs import AnalysisWorker
from codesmell.ml.models import ModelKind
from codesmell.ml.training import build_estimator


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        database={"url": f"sqlite:///{tmp_path / 'm7.db'}", "auto_migrate": True},
        api={"storage_root": tmp_path / "storage"},
        explainability={"prefer_shap": True, "top_features": 4},
        logging={"json_output": False, "level": "WARNING"},
    )


def _model_dir(path: Path) -> Path:
    path.mkdir(parents=True)
    model = build_estimator(ModelKind.LOGISTIC, seed=7)
    x = [[0.0], [1.0], [2.0], [5.0], [7.0], [9.0]]
    y = [0, 0, 0, 1, 1, 1]
    model.fit(x, y)
    model_path = path / "model.joblib"
    joblib.dump(model, model_path)
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    card = {
        "task": "binary code-smell detection",
        "smell_type": "long_parameter_list",
        "model": "logistic",
        "threshold": 0.5,
        "feature_names": ["feature__parameter_count"],
        "model_sha256": digest,
        "metrics": {"f1": 1.0},
    }
    (path / "model_card.json").write_text(json.dumps(card), encoding="utf-8")
    return path


def _project_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "sample/service.py",
            "class Service:\n"
            "    def process(self, a, b, c, d, e, f):\n"
            "        return a + b + c + d + e + f\n",
        )
    return path


def test_registry_verifies_and_copies_artifact(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    source = _model_dir(tmp_path / "model")
    with TestClient(app):
        with app.state.session_factory() as session:
            artifact = ModelRegistry(settings.api.storage_root).register(
                session, source, name="Parameters model"
            )
            stored = Path(artifact.artifact_path)
            assert stored != source
            assert (stored / "model.joblib").is_file()
            assert artifact.smell_type == "long_parameter_list"
            assert ModelRegistry(settings.api.storage_root).verify(artifact).sha256


def test_registry_rejects_tampered_model(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    source = _model_dir(tmp_path / "model")
    with TestClient(app):
        with app.state.session_factory() as session:
            artifact = ModelRegistry(settings.api.storage_root).register(session, source)
            Path(artifact.artifact_path, "model.joblib").write_bytes(b"tampered")
            with pytest.raises(ValueError, match="SHA-256"):
                ModelRegistry(settings.api.storage_root).verify(artifact)


def test_hybrid_job_persists_prediction_explanation_and_recommendation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    source_model = _model_dir(tmp_path / "model")
    project_zip = _project_zip(tmp_path / "project.zip")

    with TestClient(app) as client:
        with app.state.session_factory() as session:
            artifact = ModelRegistry(settings.api.storage_root).register(session, source_model)
            model_id = artifact.id

        with project_zip.open("rb") as handle:
            project = client.post(
                "/api/v1/projects/upload",
                files={"file": (project_zip.name, handle, "application/zip")},
            ).json()
        response = client.post(
            f"/api/v1/projects/{project['id']}/analyses",
            json={
                "analysis_kind": "hybrid",
                "model_ids": [model_id],
                "explain_predictions": True,
            },
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        worker = AnalysisWorker(settings, app.state.session_factory, worker_id="m7-test")
        assert worker.run_once() == job_id

        job = client.get(f"/api/v1/analyses/{job_id}").json()
        assert job["status"] == "succeeded"
        assert job["summary"]["analysis_kind"] == "hybrid"
        assert job["summary"]["machine_learning"]["predictions"] >= 1

        predictions = client.get(
            f"/api/v1/analyses/{job_id}/predictions?predicted=true"
        ).json()
        assert predictions["total"] >= 1
        prediction = predictions["items"][0]
        assert prediction["smell_type"] == "long_parameter_list"
        assert 0.0 <= prediction["uncertainty"] <= 0.5

        explanations = client.get(
            f"/api/v1/analyses/{job_id}/explanations"
        ).json()
        assert explanations["total"] >= 1
        assert explanations["items"][0]["top_features"][0]["feature"] == "feature__parameter_count"

        recommendations = client.get(
            f"/api/v1/analyses/{job_id}/recommendations"
        ).json()
        assert recommendations["total"] >= 1
        assert recommendations["items"][0]["actions"]

        prediction_id = prediction["id"]
        assert client.get(f"/api/v1/predictions/{prediction_id}").status_code == 200
        assert client.get(
            f"/api/v1/predictions/{prediction_id}/explanation"
        ).status_code == 200
        assert client.get(
            f"/api/v1/predictions/{prediction_id}/recommendation"
        ).status_code == 200


def test_ml_job_requires_enabled_model(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    source_model = _model_dir(tmp_path / "model")
    project_zip = _project_zip(tmp_path / "project.zip")
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            artifact = ModelRegistry(settings.api.storage_root).register(session, source_model)
            artifact.enabled = False
            session.commit()
            model_id = artifact.id
        with project_zip.open("rb") as handle:
            project = client.post(
                "/api/v1/projects/upload",
                files={"file": (project_zip.name, handle, "application/zip")},
            ).json()
        response = client.post(
            f"/api/v1/projects/{project['id']}/analyses",
            json={"analysis_kind": "ml", "model_ids": [model_id]},
        )
        assert response.status_code == 409


def test_native_explanation_is_deterministic(tmp_path: Path) -> None:
    model = build_estimator(ModelKind.LOGISTIC, seed=2)
    model.fit([[0.0], [1.0], [6.0], [8.0]], [0, 0, 1, 1])
    result = explain_prediction(
        model,
        ["feature__parameter_count"],
        [7.0],
        prefer_shap=False,
    )
    assert result.method == "linear_contribution"
    assert result.top_features[0]["direction"] == "increases_smell_risk"


def test_random_forest_uses_tree_shap_in_batch() -> None:
    model = build_estimator(ModelKind.RANDOM_FOREST, seed=3, parameters={"n_estimators": 20})
    model.fit([[0.0], [1.0], [2.0], [7.0], [8.0], [9.0]], [0, 0, 0, 1, 1, 1])
    results = explain_predictions(
        model,
        ["feature__parameter_count"],
        [[1.0], [8.0]],
        prefer_shap=True,
    )
    assert len(results) == 2
    assert all(result.method == "shap_tree" for result in results)
    assert results[1].top_features[0]["feature"] == "feature__parameter_count"
