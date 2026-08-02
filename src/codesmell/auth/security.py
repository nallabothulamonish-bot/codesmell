"""Password hashing, JWT issuance and authenticated principal types for M9."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from codesmell.config.settings import SecuritySettings

Role = Literal["admin", "analyst", "viewer"]


@dataclass(frozen=True)
class Principal:
    id: str
    email: str
    display_name: str
    role: Role
    enabled: bool = True
    synthetic: bool = False


class PasswordManager:
    """Argon2id password hashing with automatic rehash support."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=2,
            memory_cost=19_456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        try:
            return self._hasher.verify(encoded, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def needs_rehash(self, encoded: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(encoded)
        except InvalidHashError:
            return True


def create_access_token(principal: Principal, settings: SecuritySettings) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    payload = {
        "sub": principal.id,
        "email": principal.email,
        "name": principal.display_name,
        "role": principal.role,
        "iat": now,
        "nbf": now,
        "exp": expires,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": secrets.token_urlsafe(18),
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    return token, expires


def decode_access_token(token: str, settings: SecuritySettings) -> dict[str, object]:
    return jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["sub", "exp", "iat", "role"]},
    )
