"""User lifecycle and authentication service."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codesmell.auth.security import PasswordManager, Principal, Role
from codesmell.db.models import User

_passwords = PasswordManager()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("password must contain at least 8 characters")


def create_user(
    session: Session,
    *,
    email: str,
    display_name: str,
    password: str,
    role: Role,
    enabled: bool = True,
) -> User:
    normalized = normalize_email(email)
    validate_password(password)
    existing = session.scalar(select(User).where(func.lower(User.email) == normalized))
    if existing is not None:
        raise ValueError("a user with this email already exists")
    user = User(
        email=normalized,
        display_name=display_name.strip()[:160] or normalized,
        password_hash=_passwords.hash(password),
        role=role,
        enabled=enabled,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate(session: Session, email: str, password: str) -> User | None:
    normalized = normalize_email(email)
    user = session.scalar(select(User).where(func.lower(User.email) == normalized))
    if user is None or not user.enabled or not _passwords.verify(user.password_hash, password):
        return None
    if _passwords.needs_rehash(user.password_hash):
        user.password_hash = _passwords.hash(password)
    user.last_login_at = datetime.now(UTC)
    session.commit()
    session.refresh(user)
    return user


def set_password(session: Session, user: User, password: str) -> User:
    validate_password(password)
    user.password_hash = _passwords.hash(password)
    session.commit()
    session.refresh(user)
    return user


def principal_from_user(user: User) -> Principal:
    return Principal(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,  # type: ignore[arg-type]
        enabled=user.enabled,
    )



