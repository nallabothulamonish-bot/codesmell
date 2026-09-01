from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codesmell.api.dependencies import get_session, get_settings, require_authenticated, require_roles
from codesmell.api.schemas import ModelArtifactOut, ModelStateUpdate, Page
from codesmell.config.settings import Settings
from codesmell.db.models import MLPredictionRecord, ModelArtifact
from codesmell.explain import ModelRegistry

router = APIRouter(prefix="/api/v1/models", tags=["models"], dependencies=[Depends(require_authenticated)])


@router.get("", response_model=Page[ModelArtifactOut])
def list_models(
    smell: str | None = None,
    enabled: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    filters = []
    if smell:
        filters.append(ModelArtifact.smell_type == smell)
    if enabled is not None:
        filters.append(ModelArtifact.enabled.is_(enabled))
    total = session.scalar(select(func.count()).select_from(ModelArtifact).where(*filters)) or 0
    items = list(
        session.scalars(
            select(ModelArtifact)
            .where(*filters)
            .order_by(ModelArtifact.smell_type, ModelArtifact.model_kind)
            .limit(limit)
            .offset(offset)
        )
    )
    return Page(
        items=[ModelArtifactOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{model_id}", response_model=ModelArtifactOut)
def get_model(model_id: str, session: Session = Depends(get_session)) -> ModelArtifact:
    artifact = session.get(ModelArtifact, model_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="model not found")
    return artifact


@router.patch("/{model_id}", response_model=ModelArtifactOut, dependencies=[Depends(require_roles("admin"))])
def set_model_state(
    model_id: str,
    payload: ModelStateUpdate,
    session: Session = Depends(get_session),
) -> ModelArtifact:
    artifact = session.get(ModelArtifact, model_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="model not found")
    artifact.enabled = payload.enabled
    session.commit()
    session.refresh(artifact)
    return artifact


@router.delete(
    "/{model_id}",
    response_class=Response,
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles("admin"))],
)
def delete_model(
    model_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    artifact = session.get(ModelArtifact, model_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="model not found")
    used = session.scalar(
        select(func.count()).select_from(MLPredictionRecord).where(
            MLPredictionRecord.model_id == model_id
        )
    ) or 0
    if used:
        raise HTTPException(
            status_code=409,
            detail="model has persisted predictions and cannot be deleted",
        )
    ModelRegistry(settings.api.storage_root).delete_files(artifact)
    session.delete(artifact)
    session.commit()
