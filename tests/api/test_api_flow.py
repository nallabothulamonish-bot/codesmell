from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from codesmell.api.app import create_app
from codesmell.config.settings import Settings
from codesmell.jobs import AnalysisWorker


def _settings(tmp_path: Path, *, max_upload_bytes: int = 2_000_000) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        database={
            "url": f"sqlite:///{tmp_path / 'api.db'}",
            "auto_migrate": True,
        },
        api={
            "storage_root": tmp_path / "storage",
            "max_upload_bytes": max_upload_bytes,
        },
        logging={"json_output": False, "level": "WARNING"},
    )


def _project_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "sample/service.py",
            "class Service:\n"
            "    def process(self, a, b, c, d, e, f):\n"
            "        total = 0\n"
            "        for i in range(10):\n"
            "            if i % 2 == 0:\n"
            "                total += i\n"
            "        return total\n",
        )
        archive.writestr("sample/model.py", "class Model:\n    value = 1\n")
    return path


def test_upload_enqueue_worker_and_result_endpoints(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    archive = _project_zip(tmp_path / "research-project.zip")

    with TestClient(app) as client:
        with archive.open("rb") as handle:
            response = client.post(
                "/api/v1/projects/upload",
                files={"file": (archive.name, handle, "application/zip")},
                data={"name": "Research Project"},
            )
        assert response.status_code == 201
        project = response.json()
        assert project["name"] == "Research Project"
        assert project["source_type"] == "upload"

        response = client.post(
            f"/api/v1/projects/{project['id']}/analyses",
            json={"threshold_mode": "absolute", "min_severity": "low"},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]

        worker = AnalysisWorker(settings, app.state.session_factory, worker_id="test-worker")
        assert worker.run_once() == job_id

        job = client.get(f"/api/v1/analyses/{job_id}")
        assert job.status_code == 200
        assert job.json()["status"] == "succeeded"
        assert job.json()["summary"]["inventory"]["name"] == "research-project"

        metrics = client.get(f"/api/v1/analyses/{job_id}/metrics")
        assert metrics.status_code == 200
        assert metrics.json()["total"] > 0

        findings = client.get(f"/api/v1/analyses/{job_id}/findings")
        assert findings.status_code == 200
        assert findings.json()["total"] >= 1
        assert findings.json()["items"][0]["evidence"]

        events = client.get(f"/api/v1/analyses/{job_id}/events")
        assert events.status_code == 200
        assert events.json()["total"] >= 5

        project_after = client.get(f"/api/v1/projects/{project['id']}").json()
        assert project_after["fingerprint"]
        assert project_after["inventory_summary"]["file_count"] == 2


def test_upload_validation_and_github_allowlist(tmp_path: Path) -> None:
    settings = _settings(tmp_path, max_upload_bytes=10)
    app = create_app(settings)
    with TestClient(app) as client:
        bad_suffix = client.post(
            "/api/v1/projects/upload",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert bad_suffix.status_code == 400

        too_large = client.post(
            "/api/v1/projects/upload",
            files={"file": ("large.py", b"x" * 20, "text/x-python")},
        )
        assert too_large.status_code == 400

        invalid_git = client.post(
            "/api/v1/projects/github",
            json={"url": "https://example.com/org/repo", "name": "repo"},
        )
        assert invalid_git.status_code == 400

        valid_git = client.post(
            "/api/v1/projects/github",
            json={"url": "https://github.com/psf/requests", "name": "requests"},
        )
        assert valid_git.status_code == 201
        assert valid_git.json()["source_type"] == "github"


def test_queued_job_can_be_cancelled_and_project_deleted(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        uploaded = client.post(
            "/api/v1/projects/upload",
            files={"file": ("one.py", b"x = 1\n", "text/x-python")},
        ).json()
        job = client.post(
            f"/api/v1/projects/{uploaded['id']}/analyses", json={}
        ).json()

        conflict = client.delete(f"/api/v1/projects/{uploaded['id']}")
        assert conflict.status_code == 409

        cancelled = client.post(f"/api/v1/analyses/{job['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        deleted = client.delete(f"/api/v1/projects/{uploaded['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/projects/{uploaded['id']}").status_code == 404
