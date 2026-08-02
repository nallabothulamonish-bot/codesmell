from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from codesmell.api.app import create_app
from codesmell.auth.security import PasswordManager, Principal, create_access_token, decode_access_token
from codesmell.config.settings import SecuritySettings, Settings
from codesmell.db.models import User
from codesmell.jobs import AnalysisWorker
from codesmell.research import build_research_bundle


def _settings(tmp_path: Path, *, auth: bool = False) -> Settings:
    security: dict[str, object] = {
        "auth_enabled": auth,
        "jwt_secret": "m9-test-secret-that-is-definitely-long-enough",
    }
    if auth:
        security.update(
            {
                "bootstrap_admin_email": "admin@example.test",
                "bootstrap_admin_password": "StrongAdmin123",
                "bootstrap_admin_name": "Research Admin",
            }
        )
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        database={"url": f"sqlite:///{tmp_path / 'm9.db'}", "auto_migrate": True},
        api={"storage_root": tmp_path / "storage"},
        security=security,
        logging={"json_output": False, "level": "WARNING"},
    )


def _zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "app/service.py",
            "class Service:\n"
            "    def process(self, a, b, c, d, e, f):\n"
            "        total = 0\n"
            "        for i in range(20):\n"
            "            if i % 2 == 0:\n"
            "                total += i\n"
            "        return total\n",
        )
    return path


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/token", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_argon2_and_jwt_round_trip() -> None:
    manager = PasswordManager()
    encoded = manager.hash("StrongPassword123")
    assert "StrongPassword123" not in encoded
    assert manager.verify(encoded, "StrongPassword123")
    assert not manager.verify(encoded, "incorrect")

    settings = SecuritySettings(jwt_secret=SecretStr("a" * 40))
    principal = Principal("user-1", "u@example.test", "User", "analyst")
    token, expires = create_access_token(principal, settings)
    claims = decode_access_token(token, settings)
    assert claims["sub"] == "user-1"
    assert claims["role"] == "analyst"
    assert expires.isoformat()


def test_authentication_and_role_enforcement(tmp_path: Path) -> None:
    settings = _settings(tmp_path, auth=True)
    app = create_app(settings)
    with TestClient(app) as client:
        anonymous = client.get("/api/v1/projects")
        assert anonymous.status_code == 401

        admin = _login(client, "admin@example.test", "StrongAdmin123")
        created = client.post(
            "/api/v1/users",
            headers=admin,
            json={
                "email": "viewer@example.test",
                "display_name": "Read Only",
                "password": "StrongViewer123",
                "role": "viewer",
                "enabled": True,
            },
        )
        assert created.status_code == 201
        viewer = _login(client, "viewer@example.test", "StrongViewer123")
        assert client.get("/api/v1/projects", headers=viewer).status_code == 200
        forbidden = client.post(
            "/api/v1/projects/github",
            headers=viewer,
            json={"url": "https://github.com/psf/requests", "name": "requests"},
        )
        assert forbidden.status_code == 403
        assert client.get("/api/v1/users", headers=viewer).status_code == 403

        with app.state.session_factory() as session:
            admin_user = session.scalar(select(User).where(User.email == "admin@example.test"))
            assert admin_user is not None
            assert admin_user.password_hash != "StrongAdmin123"


def test_all_report_formats_and_download(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    archive = _zip(tmp_path / "report-project.zip")
    with TestClient(app) as client:
        with archive.open("rb") as handle:
            project = client.post(
                "/api/v1/projects/upload",
                files={"file": (archive.name, handle, "application/zip")},
            ).json()
        job = client.post(f"/api/v1/projects/{project['id']}/analyses", json={}).json()
        worker = AnalysisWorker(settings, app.state.session_factory, worker_id="m9-test")
        assert worker.run_once() == job["id"]

        for format_name in ("json", "csv", "html", "pdf"):
            response = client.post(
                f"/api/v1/analyses/{job['id']}/reports",
                json={"format": format_name, "title": "M9 Verification Report"},
            )
            assert response.status_code == 201
            report = response.json()
            assert report["status"] == "ready"
            assert report["content_sha256"]
            download = client.get(f"/api/v1/reports/{report['id']}/download")
            assert download.status_code == 200
            assert download.content
            if format_name == "json":
                assert json.loads(download.content)["schema_version"] == "m9-report-v1"
            elif format_name == "csv":
                bundle = tmp_path / "bundle.zip"
                bundle.write_bytes(download.content)
                with zipfile.ZipFile(bundle) as archive_file:
                    assert "findings.csv" in archive_file.namelist()
            elif format_name == "html":
                assert b"<!doctype html>" in download.content.lower()
            else:
                assert download.content.startswith(b"%PDF")

        listing = client.get(f"/api/v1/analyses/{job['id']}/reports").json()
        assert listing["total"] == 4


def test_research_bundle_outputs_tables_and_figures(tmp_path: Path) -> None:
    holdout = {
        "results": [
            {
                "status": "trained",
                "smell_type": "long_method",
                "model": "logistic",
                "test_projects": ["project-c"],
                "metrics": {
                    "support": 20,
                    "accuracy": 0.9,
                    "balanced_accuracy": 0.88,
                    "precision": 0.89,
                    "recall": 0.87,
                    "specificity": 0.9,
                    "f1": 0.88,
                    "mcc": 0.76,
                    "roc_auc": 0.94,
                    "pr_auc": 0.93,
                    "brier_score": 0.09,
                },
            }
        ]
    }
    logo = {
        "evaluated_folds": 3,
        "aggregate": {
            "long_method:logistic": {
                "smell_type": "long_method",
                "model": "logistic",
                "folds": 3,
                "macro_mean": {"f1": 0.81, "mcc": 0.67, "roc_auc": 0.9, "pr_auc": 0.88},
                "micro": {"f1": 0.82, "mcc": 0.68, "roc_auc": 0.91, "pr_auc": 0.89},
            }
        },
    }
    holdout_path = tmp_path / "holdout.json"
    logo_path = tmp_path / "logo.json"
    holdout_path.write_text(json.dumps(holdout), encoding="utf-8")
    logo_path.write_text(json.dumps(logo), encoding="utf-8")
    output = tmp_path / "research"
    result = build_research_bundle(holdout_path, logo_path, output)
    assert result["evaluated_logo_folds"] == 3
    assert (output / "holdout_metrics.csv").is_file()
    assert (output / "logo_metrics.csv").is_file()
    assert (output / "figures" / "logo_macro_f1.png").stat().st_size > 1000
    assert "Leakage controls" in (output / "RESEARCH_SUMMARY.md").read_text()


def test_production_security_guards() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            database={"auto_migrate": False},
            security={"auth_enabled": False, "jwt_secret": "x" * 40},
        )
    settings = Settings(
        environment="production",
        database={"auto_migrate": False},
        security={"auth_enabled": True, "jwt_secret": "x" * 40, "docs_enabled": False},
    )
    assert settings.is_production
