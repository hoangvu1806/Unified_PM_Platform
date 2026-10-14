"""Identity: who is calling. Mock mode issues HS256 JWTs; Keycloak comes later.

Claims mirror a Keycloak access token (``sub``, ``preferred_username``,
``name``, ``realm_access.roles``) so switching ``AUTH_MODE`` to ``keycloak``
only changes how tokens are verified, not what services read.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache

import jwt
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PLATFORM_ROLES = ("BA", "DESIGNER")
ISSUER = "platform-mock"


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    auth_mode: str = Field(default="mock")  # mock | off (tests only) | keycloak (later)
    auth_jwt_secret: str = Field(default="")
    auth_jwt_ttl_minutes: int = Field(default=480)
    auth_cookie_name: str = Field(default="platform_token")


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


@dataclass(frozen=True)
class CurrentUser:
    id: str
    username: str
    name: str
    roles: frozenset[str] = field(default_factory=frozenset)

    def has_role(self, role: str) -> bool:
        return role in self.roles


SYSTEM_USER = CurrentUser("system", "system", "System (auth off)", frozenset(PLATFORM_ROLES))


class AuthError(Exception):
    pass


def issue_token(user: CurrentUser, settings: AuthSettings | None = None) -> str:
    s = settings or get_auth_settings()
    if not s.auth_jwt_secret:
        raise AuthError("AUTH_JWT_SECRET is not configured")
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": user.id,
        "preferred_username": user.username,
        "name": user.name,
        "realm_access": {"roles": sorted(user.roles)},
        "iat": now,
        "exp": now + s.auth_jwt_ttl_minutes * 60,
    }
    return jwt.encode(claims, s.auth_jwt_secret, algorithm="HS256")


def decode_token(token: str, settings: AuthSettings | None = None) -> CurrentUser:
    s = settings or get_auth_settings()
    if s.auth_mode != "mock":
        raise AuthError(f"AUTH_MODE={s.auth_mode!r} cannot verify tokens yet")
    try:
        claims = jwt.decode(token, s.auth_jwt_secret, algorithms=["HS256"], issuer=ISSUER)
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
    roles = claims.get("realm_access", {}).get("roles", [])
    return CurrentUser(
        id=str(claims["sub"]),
        username=str(claims.get("preferred_username") or claims["sub"]),
        name=str(claims.get("name") or claims.get("preferred_username") or ""),
        roles=frozenset(r for r in roles if r in PLATFORM_ROLES),
    )
