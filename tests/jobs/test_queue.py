from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codesmell.config.settings import Settings
from codesmell.db import (
    create_db_engine,
    create_session_factory,
    upgrade_database,
)
from codesmell.db.models import AnalysisJob, Project
from codesmell.jobs.queue import (
    claim_next_job,
    enqueue_job,
    recover_stale_jobs,
    request_cancel,
    retry_job,
)


def _database(tmp_path: Path):
    settings = Settings(
        environment="test",
        workspace_root=tmp_path / "work",
        database={
            "url": f"sqlite:///{tmp_path / 'queue.db'}",
            "auto_migrate": False,
        },
        api={"storage_root": tmp_path / "data"},
    )
    upgrade_database(settings)
    engine = create_db_engine(settings)
    return engine, create_session_factory(engine)


def test_claim_is_single_transition_and_cancelled_jobs_are_skipped(tmp_path: Path) -> None:
    engine, sessions = _database(tmp_path)
    try:
        with sessions() as session:
            project = Project(name="p", source_type="github", source_url="https://github.com/a/b")
            session.add(project)
            session.commit()
            first = enqueue_job(
                session,
                project_id=project.id,
                threshold_mode="absolute",
                min_severity="low",
                max_attempts=3,
            )
            second = enqueue_job(
                session,
                project_id=project.id,
                threshold_mode="absolute",
                min_severity="low",
                max_attempts=3,
            )
            request_cancel(session, first)

        with sessions() as session:
            claimed = claim_next_job(session, "worker-a")
            assert claimed is not None
            assert claimed.id == second.id
            assert claimed.status == "running"
            assert claimed.attempts == 1

        with sessions() as session:
            assert claim_next_job(session, "worker-b") is None
    finally:
        engine.dispose()


def test_stale_jobs_are_requeued_then_fail_at_retry_limit(tmp_path: Path) -> None:
    engine, sessions = _database(tmp_path)
    try:
        with sessions() as session:
            project = Project(name="p", source_type="github", source_url="https://github.com/a/b")
            session.add(project)
            session.commit()
            job = AnalysisJob(
                project_id=project.id,
                status="running",
                attempts=1,
                max_attempts=2,
                heartbeat_at=datetime.now(UTC) - timedelta(hours=1),
            )
            session.add(job)
            session.commit()
            job_id = job.id

        with sessions() as session:
            assert recover_stale_jobs(session, 30) == 1
            recovered = session.get(AnalysisJob, job_id)
            assert recovered is not None
            assert recovered.status == "queued"

            recovered.status = "running"
            recovered.attempts = 2
            recovered.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
            session.commit()
            assert recover_stale_jobs(session, 30) == 1
            assert session.get(AnalysisJob, job_id).status == "failed"
    finally:
        engine.dispose()


def test_retry_rules(tmp_path: Path) -> None:
    engine, sessions = _database(tmp_path)
    try:
        with sessions() as session:
            project = Project(name="p", source_type="github", source_url="https://github.com/a/b")
            session.add(project)
            session.commit()
            job = AnalysisJob(
                project_id=project.id,
                status="failed",
                attempts=1,
                max_attempts=2,
            )
            session.add(job)
            session.commit()
            retried = retry_job(session, job)
            assert retried.status == "queued"

            retried.status = "failed"
            retried.attempts = 2
            session.commit()
            with pytest.raises(ValueError, match="maximum"):
                retry_job(session, retried)
    finally:
        engine.dispose()
