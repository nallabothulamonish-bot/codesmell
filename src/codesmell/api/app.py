"""FastAPI application factory for the final M9 platform."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from codesmell import __version__
from codesmell.api.routes import analyses, auth, health, models, projects, reports, users
from codesmell.api.storage import UploadStorage
from codesmell.auth.service import create_user, normalize_email
from codesmell.config.settings import Settings, get_settings
from codesmell.core.errors import CodeSmellError
from codesmell.db import (
    create_db_engine,
    create_session_factory,
    schema_is_ready,
    upgrade_database,
)
from codesmell.db.models import User


def _bootstrap_admin(app: FastAPI, settings: Settings) -> None:
    email = settings.security.bootstrap_admin_email
    password = settings.security.bootstrap_admin_password
    if not settings.security.auth_enabled or not email or password is None:
        return
    with app.state.session_factory() as session:
        exists = session.scalar(
            select(func.count()).select_from(User).where(
                func.lower(User.email) == normalize_email(email)
            )
        )
        if exists:
            return
        create_user(
            session,
            email=email,
            display_name=settings.security.bootstrap_admin_name,
            password=password.get_secret_value(),
            role="admin",
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if resolved.database.auto_migrate:
            upgrade_database(resolved)
        engine = create_db_engine(resolved)
        if not schema_is_ready(engine):
            engine.dispose()
            raise RuntimeError("database schema is not ready; run `codesmell db upgrade`")
        app.state.settings = resolved
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.storage = UploadStorage(resolved.api)
        _bootstrap_admin(app, resolved)
        yield
        engine.dispose()

    docs_enabled = resolved.security.docs_enabled
    app = FastAPI(
        title="CodeSmell API",
        description=(
            "M9 production platform for authenticated project analysis, rule and ML "
            "predictions, explainability, refactoring guidance, reports and research exports. "
            "Uploaded source is never executed."
        ),
        version=__version__,
        root_path=resolved.api.root_path,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    if resolved.security.trusted_hosts:
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=list(resolved.security.trusted_hosts)
        )
    if resolved.security.force_https:
        app.add_middleware(HTTPSRedirectMiddleware)
    if resolved.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.api.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id[:80]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = resolved.security.content_security_policy
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        principal = getattr(request.state, "principal", None)
        if request.method in {"POST", "PATCH", "DELETE"} and response.status_code < 400 and principal is not None:
            try:
                from codesmell.db.models import AuditEvent
                with app.state.session_factory() as audit_session:
                    audit_session.add(AuditEvent(
                        actor_user_id=None if principal.synthetic else principal.id,
                        action=f"http.{request.method.lower()}",
                        resource_type="api",
                        resource_id=request.url.path[:120],
                        request_id=request.state.request_id,
                        details={"status_code": response.status_code},
                    ))
                    audit_session.commit()
            except Exception:
                pass
        return response

    @app.exception_handler(CodeSmellError)
    async def _domain_error(_request: Request, exc: CodeSmellError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": exc.code, "message": exc.message, "details": exc.details},
        )

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        import logging
        logging.getLogger("codesmell.api").exception(
            "Unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred. Check server logs for details.",
            },
        )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(projects.router)
    app.include_router(models.router)
    app.include_router(analyses.router)
    app.include_router(reports.router)
    return app


app = create_app()
