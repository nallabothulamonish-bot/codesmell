"""Small audit-event helper used by privileged M9 actions."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from codesmell.auth.security import Principal
from codesmell.db.models import AuditEvent


def record_audit(
    session: Session,
    request: Request,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=None if principal.synthetic else principal.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=getattr(request.state, "request_id", None),
            details=details,
        )
    )
