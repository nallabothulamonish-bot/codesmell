from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codesmell.api.dependencies import get_session, require_roles
from codesmell.api.schemas import AuditEventOut, Page, PasswordReset, UserCreate, UserOut, UserUpdate
from codesmell.auth.service import create_user, set_password
from codesmell.db.models import User

router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(require_roles("admin"))],
)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def add_user(payload: UserCreate, session: Session = Depends(get_session)) -> User:
    try:
        return create_user(
            session,
            email=payload.email,
            display_name=payload.display_name,
            password=payload.password,
            role=payload.role,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("", response_model=Page[UserOut])
def list_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    total = session.scalar(select(func.count()).select_from(User)) or 0
    items = list(
        session.scalars(select(User).order_by(User.email).limit(limit).offset(offset))
    )
    return Page(
        items=[UserOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: str, session: Session = Depends(get_session)) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str, payload: UserUpdate, session: Session = Depends(get_session)
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    changes = payload.model_dump(exclude_unset=True)
    removes_enabled_admin = user.role == "admin" and user.enabled and (
        changes.get("role", "admin") != "admin" or changes.get("enabled", True) is False
    )
    if removes_enabled_admin:
        enabled_admins = session.scalar(
            select(func.count()).select_from(User).where(
                User.role == "admin", User.enabled.is_(True)
            )
        ) or 0
        if enabled_admins <= 1:
            raise HTTPException(status_code=409, detail="the final enabled administrator cannot be disabled or demoted")
    for key, value in changes.items():
        setattr(user, key, value)
    session.commit()
    session.refresh(user)
    return user


@router.post("/{user_id}/password", response_model=UserOut)
def reset_user_password(
    user_id: str, payload: PasswordReset, session: Session = Depends(get_session)
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    try:
        return set_password(session, user, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/audit/events", response_model=Page[AuditEventOut])
def list_audit_events(
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Page:
    from codesmell.db.models import AuditEvent

    filters = [AuditEvent.action == action] if action else []
    total = session.scalar(select(func.count()).select_from(AuditEvent).where(*filters)) or 0
    items = list(session.scalars(select(AuditEvent).where(*filters).order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)))
    return Page(
        items=[AuditEventOut.model_validate(item).model_dump() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
