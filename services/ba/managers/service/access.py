"""Platform access control for BA routes (Sprint 3).

Every BA router depends on :func:`ba_access`. It authenticates the caller and,
when the path carries ``{session_id}``, checks the caller's membership in the
feature's project (``ba_packages.project_id``):

* GET/HEAD — any project member may read (features, chat history, documents);
* other methods — need role BA (or ADMIN) in that project.

Routes without a session in the path (create/list features, wiki) call
:func:`require_project` themselves.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from platform_core.fastapi import (
    auth_disabled,
    authenticate,
    get_current_user,
    require_project,
)

from managers.database.connection import SessionLocal
from managers.database.models import BaPackageModel

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
BA_ROLE = "BA"

__all__ = [
    "BA_ROLE",
    "ba_access",
    "current_username",
    "package_project_id",
    "require_company_wiki_admin",
    "require_project",
]


def package_project_id(session_id: str) -> tuple[bool, str | None]:
    """(exists, project_id) for a BA feature."""
    db = SessionLocal()
    try:
        pkg = db.get(BaPackageModel, session_id)
        return (pkg is not None, getattr(pkg, "project_id", None) if pkg else None)
    finally:
        db.close()


async def ba_access(request: Request) -> None:
    await authenticate(request)
    session_id = request.path_params.get("session_id")
    if not session_id or auth_disabled():
        return
    exists, project_id = package_project_id(str(session_id))
    if not exists:
        return  # the handler answers 404 as before
    if not project_id:
        raise HTTPException(
            403,
            detail={"code": "PROJECT_UNASSIGNED", "message": "Feature has no project (run legacy assignment)"},
        )
    write = request.method.upper() not in READ_METHODS
    require_project(project_id, BA_ROLE if write else None)


def current_username(default: str | None = "ba.lead") -> str | None:
    """Audit actor: the logged-in user (``default`` only when auth is off)."""
    if auth_disabled():
        return default
    return get_current_user().username


def require_company_wiki_admin(project_id: str | None) -> None:
    """Company wiki writes need ADMIN in the project the request comes from."""
    if auth_disabled():
        return
    roles = require_project(project_id, BA_ROLE)
    if "ADMIN" not in roles:
        raise HTTPException(
            403, detail={"code": "ADMIN_REQUIRED", "message": "Only project ADMINs may change the company wiki"}
        )
