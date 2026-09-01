from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codesmell.api.audit import record_audit
from codesmell.api.dependencies import get_session, get_settings, require_authenticated, require_roles
from codesmell.api.schemas import Page, ReportCreate, ReportOut
from codesmell.auth.security import Principal
from codesmell.config.settings import Settings
from codesmell.db.models import AnalysisJob, GeneratedReport
from codesmell.reports import generate_report

router = APIRouter(prefix="/api/v1", tags=["reports"], dependencies=[Depends(require_authenticated)])


@router.post(
    "/analyses/{job_id}/reports",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("admin", "analyst"))],
)
def create_report(
    job_id: str,
    payload: ReportCreate,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_authenticated),
) -> GeneratedReport:
    job = session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    if job.status != "succeeded":
        raise HTTPException(status_code=409, detail="analysis has not succeeded")
    title = (payload.title or f"CodeSmell Analysis Report - {job_id[:8]}").strip()[:255]
    report = GeneratedReport(
        job_id=job_id,
        requested_by=None if principal.synthetic else principal.id,
        format=payload.format,
        status="generating",
        title=title,
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    try:
        artifact = generate_report(session, settings, report)
        report.status = "ready"
        report.stored_path = str(artifact.path)
        report.filename = artifact.filename
        report.media_type = artifact.media_type
        report.size_bytes = artifact.size_bytes
        report.content_sha256 = artifact.sha256
        report.completed_at = datetime.now(UTC)
        record_audit(
            session,
            request,
            principal,
            action="report.generate",
            resource_type="report",
            resource_id=report.id,
            details={"job_id": job_id, "format": payload.format},
        )
        session.commit()
        session.refresh(report)
        return report
    except Exception as exc:
        report.status = "failed"
        report.error_message = str(exc)[:2000]
        report.completed_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(status_code=500, detail="report generation failed") from exc


@router.get("/analyses/{job_id}/reports", response_model=Page[ReportOut])
def list_reports(
    job_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    if session.get(AnalysisJob, job_id) is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    predicate = GeneratedReport.job_id == job_id
    total = session.scalar(select(func.count()).select_from(GeneratedReport).where(predicate)) or 0
    items = list(session.scalars(select(GeneratedReport).where(predicate).order_by(GeneratedReport.created_at.desc()).limit(limit).offset(offset)))
    return Page(
        items=[ReportOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(report_id: str, session: Session = Depends(get_session)) -> GeneratedReport:
    report = session.get(GeneratedReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, session: Session = Depends(get_session)) -> FileResponse:
    report = session.get(GeneratedReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    if report.status != "ready" or not report.stored_path:
        raise HTTPException(status_code=409, detail="report is not ready")
    path = Path(report.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="report file is unavailable")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if report.content_sha256 and digest != report.content_sha256:
        raise HTTPException(status_code=409, detail="report integrity verification failed")
    return FileResponse(path, media_type=report.media_type, filename=report.filename)


@router.delete(
    "/reports/{report_id}",
    response_class=Response,
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles("admin"))],
)
def delete_report(
    report_id: str,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_authenticated),
) -> Response:
    report = session.get(GeneratedReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    if report.stored_path:
        shutil.rmtree(Path(report.stored_path).parent, ignore_errors=True)
    record_audit(
        session,
        request,
        principal,
        action="report.delete",
        resource_type="report",
        resource_id=report.id,
    )
    session.delete(report)
    session.commit()
