"""FastAPI glue: authenticate every request and expose the caller to handlers.

Services add ``Depends(authenticate)`` at router level. Handlers that do not
take a ``Request`` read the caller with :func:`get_current_user`, which is
backed by a context variable set by the dependency.
"""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import HTTPException, Request

from platform_core.auth import SYSTEM_USER, AuthError, CurrentUser, decode_token, get_auth_settings
from platform_core.projects import ProjectAccessError, check_project

_current_user: ContextVar[CurrentUser | None] = ContextVar("platform_current_user", default=None)


def _token_from(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(get_auth_settings().auth_cookie_name) or None


def resolve_user(request: Request) -> CurrentUser:
    settings = get_auth_settings()
    if settings.auth_mode == "off":
        return SYSTEM_USER
    token = _token_from(request)
    if not token:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Login required"})
    try:
        return decode_token(token, settings)
    except AuthError as exc:
        raise HTTPException(401, detail={"code": "AUTH_INVALID", "message": str(exc)}) from exc


async def authenticate(request: Request) -> CurrentUser:
    """Router dependency: 401 without a valid token; stores the caller."""
    user = resolve_user(request)
    request.state.user = user
    _current_user.set(user)
    return user


def get_current_user() -> CurrentUser:
    user = _current_user.get()
    if user is None:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Login required"})
    return user


def auth_disabled() -> bool:
    return get_auth_settings().auth_mode == "off"


def require_project(project_id: str | None, write_role: str | None = None) -> frozenset[str]:
    """403/400 unless the current caller may read (or write with ``write_role``)."""
    if auth_disabled():
        return frozenset({"ADMIN"})
    try:
        return check_project(get_current_user(), project_id, write_role)
    except ProjectAccessError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc
