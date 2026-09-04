"""Persistent database-backed analysis queue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from codesmell.db.models import AnalysisJob, JobEvent

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def enqueue_job(
    session: Session,
    *,
    project_id: str,
    threshold_mode: str,
    min_severity: str,
    max_attempts: int,
    analysis_kind: str = "rule",
    model_ids: list[str] | None = None,
    explain_predictions: bool = True,
) -> AnalysisJob:
    job = AnalysisJob(
        project_id=project_id,
        threshold_mode=threshold_mode,
        min_severity=min_severity,
        max_attempts=max_attempts,
        analysis_kind=analysis_kind,
        model_ids=model_ids,
        explain_predictions=explain_predictions,
        status="queued",
        progress=0,
        progress_message="queued",
    )
    session.add(job)
    session.flush()
    session.add(
        JobEvent(job_id=job.id, event_type="queued", message="Analysis queued")
    )
    session.commit()
    session.refresh(job)
    return job


def claim_next_job(session: Session, worker_id: str) -> AnalysisJob | None:
    """Atomically claim the oldest queued job.

    The conditional UPDATE is the concurrency guard. Two workers can read the
    same candidate, but only one can transition it from queued to running.
    """
    while True:
        candidate = session.scalar(
            select(AnalysisJob.id)
            .where(
                AnalysisJob.status == "queued",
                AnalysisJob.cancel_requested.is_(False),
                AnalysisJob.attempts < AnalysisJob.max_attempts,
            )
            .order_by(AnalysisJob.queued_at, AnalysisJob.id)
            .limit(1)
        )
        if candidate is None:
            session.rollback()
            return None

        now = utcnow()
        result = session.execute(
            update(AnalysisJob)
            .where(
                AnalysisJob.id == candidate,
                AnalysisJob.status == "queued",
                AnalysisJob.cancel_requested.is_(False),
            )
            .values(
                status="running",
                attempts=AnalysisJob.attempts + 1,
                locked_by=worker_id,
                locked_at=now,
                heartbeat_at=now,
                started_at=now,
                completed_at=None,
                progress=1,
                progress_message="claimed by worker",
                error_code=None,
                error_message=None,
            )
        )
        if result.rowcount == 1:
            session.add(
                JobEvent(
                    job_id=candidate,
                    event_type="started",
                    message=f"Claimed by worker {worker_id}",
                )
            )
            session.commit()
            return session.get(AnalysisJob, candidate)
        session.rollback()


def recover_stale_jobs(session: Session, stale_after_seconds: int) -> int:
    cutoff = utcnow() - timedelta(seconds=stale_after_seconds)
    stale_ids = list(
        session.scalars(
            select(AnalysisJob.id).where(
                AnalysisJob.status == "running",
                AnalysisJob.heartbeat_at.is_not(None),
                AnalysisJob.heartbeat_at < cutoff,
            )
        )
    )
    if not stale_ids:
        return 0

    for job_id in stale_ids:
        job = session.get(AnalysisJob, job_id)
        if job is None:
            continue
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.completed_at = utcnow()
            job.error_code = "worker_stale"
            job.error_message = "Worker heartbeat expired and retry limit was reached"
            event_type = "failed"
            message = "Stale worker detected; retry limit reached"
        else:
            job.status = "queued"
            job.queued_at = utcnow()
            job.progress = 0
            job.progress_message = "requeued after stale worker"
            job.locked_by = None
            job.locked_at = None
            job.heartbeat_at = None
            event_type = "requeued"
            message = "Stale worker detected; job requeued"
        session.add(JobEvent(job_id=job.id, event_type=event_type, message=message))
    session.commit()
    return len(stale_ids)


def request_cancel(session: Session, job: AnalysisJob) -> AnalysisJob:
    if job.status in TERMINAL_STATUSES:
        return job
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.completed_at = utcnow()
        job.progress_message = "cancelled before execution"
    session.add(
        JobEvent(job_id=job.id, event_type="cancel_requested", message="Cancellation requested")
    )
    session.commit()
    session.refresh(job)
    return job


def retry_job(session: Session, job: AnalysisJob) -> AnalysisJob:
    if job.status not in {"failed", "cancelled"}:
        raise ValueError("only failed or cancelled jobs can be retried")
    if job.attempts >= job.max_attempts:
        job.max_attempts = job.attempts + 3
    job.attempts = 0
    job.status = "queued"
    job.cancel_requested = False
    job.queued_at = utcnow()
    job.started_at = None
    job.completed_at = None
    job.locked_by = None
    job.locked_at = None
    job.heartbeat_at = None
    job.progress = 0
    job.progress_message = "queued for retry"
    job.error_code = None
    job.error_message = None
    session.add(JobEvent(job_id=job.id, event_type="retried", message="Job queued for retry"))
    session.commit()
    session.refresh(job)
    return job


def jobs_query(*, project_id: str | None = None, status: str | None = None) -> Select[tuple[AnalysisJob]]:
    statement = select(AnalysisJob)
    if project_id:
        statement = statement.where(AnalysisJob.project_id == project_id)
    if status:
        statement = statement.where(AnalysisJob.status == status)
    return statement.order_by(AnalysisJob.created_at.desc())
