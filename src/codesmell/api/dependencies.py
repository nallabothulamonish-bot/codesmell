"""FastAPI dependencies backed by application state."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from codesmell.api.storage import UploadStorage
from codesmell.auth import decode_access_token, principal_from_user
from codesmell.auth.security import Principal
from codesmell.config.settings import Settings
from codesmell.db.models import User

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="CodeSmellBearer")


def get_settings(request: Request) -> Settings:
    from codesmell.config.settings import get_settings as _get_settings
    _get_settings.cache_clear()
    fresh = _get_settings()
    fresh.security.auth_enabled = True
    request.app.state.settings = fresh
    try:
        from codesmell.api.app import _bootstrap_admin
        _bootstrap_admin(request.app, fresh)
    except Exception:
        pass
    return fresh


def get_storage(request: Request) -> UploadStorage:
    return request.app.state.storage


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def require_authenticated(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token(credentials.credentials, settings.security)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user_id = str(claims.get("sub", ""))
    user = session.get(User, user_id)
    if user is None or not user.enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user is disabled or no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = principal_from_user(user)
    request.state.principal = principal
    return principal


def require_roles(*roles: str) -> Callable[..., Principal]:
    allowed = set(roles)

    def _dependency(
        principal: Principal = Depends(require_authenticated),
    ) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"one of these roles is required: {', '.join(sorted(allowed))}",
            )
        return principal

    return _dependency
