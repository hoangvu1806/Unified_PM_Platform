"""Load and persist the single feature/session control key."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import HTTPException
from google.adk.events import Event, EventActions

from agents.ba_agent.constants import (
    DEFAULT_SECTION,
    DEFAULT_TICKET_TYPE,
    STATE_ACTIVE_SECTION,
    STATE_ACTIVE_USER_STORY_ID,
    STATE_FEATURE_STATUS,
    STATE_TICKET_TYPE,
)
from managers.control.status import STATUS_DRAFT, normalize_feature_status
from managers.database import connection as db_connection
from managers.database.models import BaPackageModel


def _session_service():
    from managers.runner_context import APP_NAME, get_session_service

    return APP_NAME, get_session_service()

CONTROL_USER_ID = "ba-user"


def project_id_for_session(session_id: str) -> str:
    """Stable unique project_id per BA session / dự án (not a shared default)."""
    digest = hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:12].upper()
    return f"PRJ-{digest}"


def resolve_project_id(
    state: dict[str, Any] | None = None,
    *,
    session_id: str | None = None,
) -> str:
    """Prefer stored project_id; else hash session_id. Never invent a shared MES id."""
    state = state or {}
    pid = state.get("project_id")
    if pid:
        return str(pid)
    sid = session_id or state.get("session_id") or state.get("feature_id")
    if sid:
        return project_id_for_session(str(sid))
    return "PRJ-UNKNOWN"


def _package_status(session_id: str) -> str | None:
    db = db_connection.SessionLocal()
    try:
        pkg = db.get(BaPackageModel, session_id)
        if pkg is None:
            return None
        return getattr(pkg, "feature_status", None)
    except Exception:
        return None
    finally:
        db.close()


def write_package_status(session_id: str, feature_status: str) -> None:
    db = db_connection.SessionLocal()
    try:
        pkg = db.get(BaPackageModel, session_id)
        if pkg is None:
            return
        pkg.feature_status = feature_status
        db.commit()
    except Exception:
        db.rollback()
        return
    finally:
        db.close()


async def get_adk_session(session_id: str, user_id: str | None = None):
    """Return the ADK session for this feature, trying the control user first."""
    app_name, service = _session_service()
    candidates = []
    if user_id:
        candidates.append(user_id)
    if CONTROL_USER_ID not in candidates:
        candidates.append(CONTROL_USER_ID)
    if "default-user" not in candidates:
        candidates.append("default-user")

    for uid in candidates:
        session = await service.get_session(
            app_name=app_name,
            user_id=uid,
            session_id=session_id,
        )
        if session is not None:
            return session, uid
    return None, user_id or CONTROL_USER_ID


async def load_control_state(
    session_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Session/feature identity + status. ADK state wins; package is fallback."""
    session, resolved_user = await get_adk_session(session_id, user_id)
    state = dict(session.state) if session is not None else {}
    if not state.get(STATE_FEATURE_STATUS):
        pkg_status = _package_status(session_id)
        if pkg_status:
            state[STATE_FEATURE_STATUS] = pkg_status
    state.setdefault("session_id", session_id)
    state.setdefault("feature_id", session_id)
    state.setdefault("project_id", project_id_for_session(session_id))
    state.setdefault(STATE_FEATURE_STATUS, STATUS_DRAFT)
    state.setdefault(STATE_TICKET_TYPE, DEFAULT_TICKET_TYPE)
    state.setdefault(STATE_ACTIVE_SECTION, DEFAULT_SECTION)
    state["_control_user_id"] = resolved_user
    state[STATE_FEATURE_STATUS] = normalize_feature_status(
        state.get(STATE_FEATURE_STATUS)
    )
    return state


async def persist_control_delta(
    session_id: str,
    updates: dict[str, Any],
    user_id: str | None = None,
) -> dict[str, Any]:
    """Write control fields onto the ADK session (and package status if present)."""
    app_name, service = _session_service()
    session, resolved_user = await get_adk_session(session_id, user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Feature session not found")

    event = Event(
        author="control_plane",
        actions=EventActions(stateDelta=updates),
    )
    await service.append_event(session, event)
    if STATE_FEATURE_STATUS in updates:
        write_package_status(session_id, str(updates[STATE_FEATURE_STATUS]))

    refreshed = await service.get_session(
        app_name=app_name,
        user_id=resolved_user,
        session_id=session_id,
    )
    return dict(refreshed.state) if refreshed else {**dict(session.state), **updates}


def initial_feature_state(
    session_id: str,
    *,
    title: str,
    description: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "feature_id": session_id,
        "feature_title": title,
        "feature_description": description,
        "project_id": project_id or project_id_for_session(session_id),
        STATE_FEATURE_STATUS: STATUS_DRAFT,
        "package_exported": False,
        STATE_TICKET_TYPE: DEFAULT_TICKET_TYPE,
        STATE_ACTIVE_SECTION: DEFAULT_SECTION,
        STATE_ACTIVE_USER_STORY_ID: None,
    }
