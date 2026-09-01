from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from codesmell.api.dependencies import get_session, get_settings, require_authenticated
from codesmell.api.schemas import LoginRequest, TokenOut, UserCreate, UserOut
from codesmell.auth import authenticate, create_access_token, principal_from_user
from codesmell.auth.security import Principal
from codesmell.config.settings import Settings

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post("/token", response_model=TokenOut)
def login(
    payload: LoginRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenOut:
    if not settings.security.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="authentication is disabled for this deployment",
        )
    user = authenticate(session, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = principal_from_user(user)
    token, expires = create_access_token(principal, settings.security)
    return TokenOut(
        access_token=token,
        expires_at=expires,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(principal: Principal = Depends(require_authenticated)) -> UserOut:
    now = datetime.now(UTC)
    return UserOut(
        id=principal.id,
        email=principal.email,
        display_name=principal.display_name,
        role=principal.role,
        enabled=principal.enabled,
        last_login_at=None,
        created_at=now,
        updated_at=now,
    )


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenOut:
    if not settings.security.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="authentication is disabled for this deployment",
        )
    from codesmell.auth.service import create_user
    try:
        user = create_user(
            session,
            email=payload.email,
            display_name=payload.display_name,
            password=payload.password,
            role=payload.role,
            enabled=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    principal = principal_from_user(user)
    token, expires = create_access_token(principal, settings.security)
    return TokenOut(
        access_token=token,
        expires_at=expires,
        user=UserOut.model_validate(user),
    )
