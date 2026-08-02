from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codesmell.api.dependencies import get_session, get_settings, require_authenticated, require_roles
from codesmell.api.schemas import (
    AnalysisCreate,
    AnalysisOut,
    ExplanationOut,
    FindingOut,
    JobEventOut,
    MetricOut,
    Page,
    PredictionOut,
    RecommendationOut,
)
from codesmell.config.settings import Settings
from codesmell.db.models import (
    AnalysisJob,
    EntityMetricRecord,
    FindingRecord,
    JobEvent,
    MLPredictionRecord,
    ModelArtifact,
    PredictionExplanation,
    Project,
    RecommendationRecord,
)
from codesmell.jobs.queue import enqueue_job, jobs_query, request_cancel, retry_job

router = APIRouter(prefix="/api/v1", tags=["analyses"], dependencies=[Depends(require_authenticated)])


@router.post(
    "/projects/{project_id}/analyses",
    response_model=AnalysisOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_roles("admin", "analyst"))],
)
def create_analysis(
    project_id: str,
    payload: AnalysisCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AnalysisJob:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if payload.analysis_kind in {"ml", "hybrid"}:
        filters = [ModelArtifact.enabled.is_(True)]
        if payload.model_ids:
            filters.append(ModelArtifact.id.in_(payload.model_ids))
        available = list(session.scalars(select(ModelArtifact).where(*filters)))
        if not available:
            raise HTTPException(
                status_code=409,
                detail="no enabled ML models match this analysis request",
            )
        if payload.model_ids and len(available) != len(payload.model_ids):
            found = {item.id for item in available}
            missing = sorted(set(payload.model_ids) - found)
            raise HTTPException(
                status_code=409,
                detail={"message": "some models are missing or disabled", "model_ids": missing},
            )
    return enqueue_job(
        session,
        project_id=project_id,
        threshold_mode=payload.threshold_mode,
        min_severity=payload.min_severity,
        max_attempts=payload.max_attempts or settings.worker.default_max_attempts,
        analysis_kind=payload.analysis_kind,
        model_ids=payload.model_ids,
        explain_predictions=payload.explain_predictions,
    )


@router.get("/analyses", response_model=Page[AnalysisOut])
def list_analyses(
    project_id: str | None = None,
    job_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    statement = jobs_query(project_id=project_id, status=job_status)
    count_statement = select(func.count()).select_from(AnalysisJob)
    if project_id:
        count_statement = count_statement.where(AnalysisJob.project_id == project_id)
    if job_status:
        count_statement = count_statement.where(AnalysisJob.status == job_status)
    total = session.scalar(count_statement) or 0
    items = list(session.scalars(statement.limit(limit).offset(offset)))
    return Page(
        items=[AnalysisOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/analyses/{job_id}", response_model=AnalysisOut)
def get_analysis(job_id: str, session: Session = Depends(get_session)) -> AnalysisJob:
    job = session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return job


@router.post("/analyses/{job_id}/cancel", response_model=AnalysisOut, dependencies=[Depends(require_roles("admin", "analyst"))])
def cancel_analysis(job_id: str, session: Session = Depends(get_session)) -> AnalysisJob:
    job = session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return request_cancel(session, job)


@router.post("/analyses/{job_id}/retry", response_model=AnalysisOut, dependencies=[Depends(require_roles("admin", "analyst"))])
def retry_analysis(job_id: str, session: Session = Depends(get_session)) -> AnalysisJob:
    job = session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    try:
        return retry_job(session, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/analyses/{job_id}/findings", response_model=Page[FindingOut])
def list_findings(
    job_id: str,
    smell: str | None = None,
    severity: str | None = None,
    path: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    _require_job(session, job_id)
    filters = [FindingRecord.job_id == job_id]
    if smell:
        filters.append(FindingRecord.smell_type == smell)
    if severity:
        filters.append(FindingRecord.severity == severity)
    if path:
        filters.append(FindingRecord.relative_path.contains(path))
    total = session.scalar(
        select(func.count()).select_from(FindingRecord).where(*filters)
    ) or 0
    items = list(
        session.scalars(
            select(FindingRecord)
            .where(*filters)
            .order_by(FindingRecord.relative_path, FindingRecord.start_line)
            .limit(limit)
            .offset(offset)
        )
    )
    return Page(
        items=[FindingOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/analyses/{job_id}/metrics", response_model=Page[MetricOut])
def list_metrics(
    job_id: str,
    entity_type: str | None = None,
    path: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    _require_job(session, job_id)
    filters = [EntityMetricRecord.job_id == job_id]
    if entity_type:
        filters.append(EntityMetricRecord.entity_type == entity_type)
    if path:
        filters.append(EntityMetricRecord.relative_path.contains(path))
    total = session.scalar(
        select(func.count()).select_from(EntityMetricRecord).where(*filters)
    ) or 0
    items = list(
        session.scalars(
            select(EntityMetricRecord)
            .where(*filters)
            .order_by(EntityMetricRecord.relative_path, EntityMetricRecord.start_line)
            .limit(limit)
            .offset(offset)
        )
    )
    return Page(
        items=[MetricOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/analyses/{job_id}/events", response_model=Page[JobEventOut])
def list_events(
    job_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    _require_job(session, job_id)
    total = session.scalar(
        select(func.count()).select_from(JobEvent).where(JobEvent.job_id == job_id)
    ) or 0
    items = list(
        session.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.created_at, JobEvent.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return Page(
        items=[JobEventOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/predictions/{prediction_id}", response_model=PredictionOut)
def get_prediction(
    prediction_id: int, session: Session = Depends(get_session)
) -> MLPredictionRecord:
    prediction = session.get(MLPredictionRecord, prediction_id)
    if prediction is None:
        raise HTTPException(status_code=404, detail="prediction not found")
    return prediction


@router.get(
    "/predictions/{prediction_id}/explanation", response_model=ExplanationOut
)
def get_prediction_explanation(
    prediction_id: int, session: Session = Depends(get_session)
) -> PredictionExplanation:
    explanation = session.scalar(
        select(PredictionExplanation).where(
            PredictionExplanation.prediction_id == prediction_id
        )
    )
    if explanation is None:
        raise HTTPException(status_code=404, detail="explanation not found")
    return explanation


@router.get(
    "/predictions/{prediction_id}/recommendation", response_model=RecommendationOut
)
def get_prediction_recommendation(
    prediction_id: int, session: Session = Depends(get_session)
) -> RecommendationRecord:
    recommendation = session.scalar(
        select(RecommendationRecord).where(
            RecommendationRecord.prediction_id == prediction_id
        )
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    return recommendation


@router.get("/analyses/{job_id}/predictions", response_model=Page[PredictionOut])
def list_predictions(
    job_id: str,
    smell: str | None = None,
    predicted: bool | None = None,
    model_id: str | None = None,
    path: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    _require_job(session, job_id)
    filters = [MLPredictionRecord.job_id == job_id]
    if smell:
        filters.append(MLPredictionRecord.smell_type == smell)
    if predicted is not None:
        filters.append(MLPredictionRecord.prediction.is_(predicted))
    if model_id:
        filters.append(MLPredictionRecord.model_id == model_id)
    if path:
        filters.append(MLPredictionRecord.relative_path.contains(path))
    total = session.scalar(
        select(func.count()).select_from(MLPredictionRecord).where(*filters)
    ) or 0
    items = list(
        session.scalars(
            select(MLPredictionRecord)
            .where(*filters)
            .order_by(MLPredictionRecord.probability.desc(), MLPredictionRecord.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return Page(
        items=[PredictionOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/analyses/{job_id}/explanations", response_model=Page[ExplanationOut]
)
def list_explanations(
    job_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    _require_job(session, job_id)
    predicate = MLPredictionRecord.job_id == job_id
    total = session.scalar(
        select(func.count())
        .select_from(PredictionExplanation)
        .join(MLPredictionRecord)
        .where(predicate)
    ) or 0
    items = list(
        session.scalars(
            select(PredictionExplanation)
            .join(MLPredictionRecord)
            .where(predicate)
            .order_by(PredictionExplanation.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return Page(
        items=[ExplanationOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/analyses/{job_id}/recommendations", response_model=Page[RecommendationOut]
)
def list_recommendations(
    job_id: str,
    smell: str | None = None,
    priority: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    _require_job(session, job_id)
    filters = [RecommendationRecord.job_id == job_id]
    if smell:
        filters.append(RecommendationRecord.smell_type == smell)
    if priority:
        filters.append(RecommendationRecord.priority == priority)
    total = session.scalar(
        select(func.count()).select_from(RecommendationRecord).where(*filters)
    ) or 0
    items = list(
        session.scalars(
            select(RecommendationRecord)
            .where(*filters)
            .order_by(RecommendationRecord.priority.desc(), RecommendationRecord.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return Page(
        items=[RecommendationOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def _require_job(session: Session, job_id: str) -> AnalysisJob:
    job = session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return job
