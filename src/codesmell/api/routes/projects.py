from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codesmell.api.dependencies import get_session, get_settings, get_storage, require_authenticated, require_roles
from codesmell.api.schemas import GitProjectCreate, Page, ProjectOut
from codesmell.api.storage import UploadRejected, UploadStorage
from codesmell.config.settings import Settings
from codesmell.container import build_container
from codesmell.db.models import AnalysisJob, GeneratedReport, Project

router = APIRouter(prefix="/api/v1/projects", tags=["projects"], dependencies=[Depends(require_authenticated)])


@router.post("/upload", response_model=ProjectOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles("admin", "analyst"))])
async def upload_project(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    session: Session = Depends(get_session),
    storage: UploadStorage = Depends(get_storage),
) -> Project:
    try:
        stored = await storage.save(file)
    except UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    project_name = (name or Path(stored.original_filename).stem).strip()[:160]
    if not project_name:
        project_name = "project"
    project = Project(
        name=project_name,
        source_type="upload",
        stored_path=str(stored.path),
        original_filename=stored.original_filename,
        content_sha256=stored.sha256,
        status="registered",
    )
    try:
        session.add(project)
        session.commit()
        session.refresh(project)
        return project
    except Exception:
        session.rollback()
        storage.delete(str(stored.path))
        raise


@router.post("/github", response_model=ProjectOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles("admin", "analyst"))])
def register_github_project(
    payload: GitProjectCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Project:
    url = str(payload.url)
    fetcher = build_container(settings).repository_fetcher
    if not fetcher.supports(url):
        raise HTTPException(
            status_code=400,
            detail="URL must be an allowed public HTTPS Git repository",
        )
    parsed = urlparse(url)
    default_name = Path(parsed.path.rstrip("/")).stem or "repository"
    project = Project(
        name=(payload.name or default_name)[:160],
        source_type="github",
        source_url=url,
        status="registered",
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.get("", response_model=Page[ProjectOut])
def list_projects(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    total = session.scalar(select(func.count()).select_from(Project)) or 0
    items = list(
        session.scalars(
            select(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)
        )
    )
    return Page(
        items=[ProjectOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(get_session)) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_roles("admin", "analyst"))])
def delete_project(
    project_id: str,
    session: Session = Depends(get_session),
    storage: UploadStorage = Depends(get_storage),
) -> None:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    active = session.scalar(
        select(func.count())
        .select_from(AnalysisJob)
        .where(
            AnalysisJob.project_id == project_id,
            AnalysisJob.status.in_(["queued", "running"]),
        )
    ) or 0
    if active:
        raise HTTPException(status_code=409, detail="project has active analysis jobs")
    stored_path = project.stored_path
    report_paths = list(session.scalars(
        select(GeneratedReport.stored_path)
        .join(AnalysisJob, GeneratedReport.job_id == AnalysisJob.id)
        .where(AnalysisJob.project_id == project_id, GeneratedReport.stored_path.is_not(None))
    ))
    session.delete(project)
    session.commit()
    storage.delete(stored_path)
    for report_path in report_paths:
        if report_path:
            shutil.rmtree(Path(report_path).parent, ignore_errors=True)
