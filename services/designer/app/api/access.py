"""Platform access control for Designer routes (Sprint 3).

Router dependency: authenticate, then — when the path carries ``{session_id}``
or ``{run_id}`` — check the caller against the session's project:

* GET/HEAD (sessions, runs, events SSE, preview, download): any member;
* other methods (messages, reviews, retry, cancel, delete): DESIGNER or ADMIN.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request
from platform_core.fastapi import auth_disabled, authenticate, get_current_user, require_project

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DESIGNER_ROLE = "DESIGNER"


PUBLIC_PATHS = frozenset({"/api/v1/health"})


async def designer_access(request: Request) -> None:
    if request.url.path in PUBLIC_PATHS:
        return  # container healthcheck
    await authenticate(request)
    if auth_disabled():
        return
    store = request.app.state.store
    if "session_id" in request.path_params:
        exists, project_id = await store.session_project(request.path_params["session_id"])
    elif "run_id" in request.path_params:
        exists, project_id = await store.run_project(request.path_params["run_id"])
    else:
        return
    if not exists:
        return  # handlers answer 404 as before
    if not project_id:
        raise HTTPException(
            403, detail={"code": "PROJECT_UNASSIGNED", "message": "Session has no project (run legacy assignment)"}
        )
    write = request.method.upper() not in READ_METHODS
    require_project(project_id, DESIGNER_ROLE if write else None)


def current_user_id() -> str | None:
    return None if auth_disabled() else get_current_user().id


def current_username() -> str | None:
    return None if auth_disabled() else get_current_user().username


async def handoff_secret(request: Request) -> None:
    """Service-to-service: BA presents X-Agent-Secret when one is configured."""
    expected = request.app.state.settings.designer_shared_secret
    if not expected:
        return
    given = request.headers.get("x-agent-secret", "")
    if not hmac.compare_digest(given, expected):
        raise HTTPException(401, detail={"code": "AGENT_SECRET_INVALID", "message": "Invalid X-Agent-Secret"})
