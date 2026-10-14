"""Top-level router for the unified BA Agent graph."""

from __future__ import annotations

import logging

from google.adk import Context
from google.adk.workflow import node

from agents.ba_agent.constants import (
    DEFAULT_SECTION,
    DEFAULT_TICKET_TYPE,
    IMPLEMENTED_SECTIONS,
    IMPLEMENTED_TICKET_TYPES,
    ROUTE_BR,
    ROUTE_FD,
    ROUTE_LOCKED,
    ROUTE_STUB,
    ROUTE_UC,
    ROUTE_VALIDATE,
    ROUTE_WF,
    SECTION_TO_ROUTE,
    STATE_ACTIVE_SECTION,
    STATE_TICKET_TYPE,
    STATE_VALIDATE_ACTION,
    VALIDATE_MESSAGE_PREFIX,
    SECTION_VALIDATION,
)
from agents.ba_agent.section_gate import can_access_section, sync_sections_status_from_flags

logger = logging.getLogger(__name__)


def _user_text(ctx: Context) -> str:
    content = getattr(ctx, "user_content", None)
    if content is None:
        return ""
    parts = getattr(content, "parts", None) or []
    if not parts:
        return ""
    return getattr(parts[0], "text", "") or ""


def route_ba_turn(ctx: Context) -> str:
    """Pure routing logic — used by the graph node and by unit tests."""
    state = ctx.state
    user_input = _user_text(ctx)

    ticket_type = state.get(STATE_TICKET_TYPE) or DEFAULT_TICKET_TYPE
    active_section = state.get(STATE_ACTIVE_SECTION) or DEFAULT_SECTION
    state[STATE_TICKET_TYPE] = ticket_type
    state[STATE_ACTIVE_SECTION] = active_section
    state.setdefault("artifacts", {})
    state.setdefault("flags", {})
    state.setdefault("sections_status", {})
    state.setdefault("feature_status", "DRAFT")
    sid = str(state.get("session_id") or state.get("feature_id") or "")
    if sid:
        from managers.control.session import project_id_for_session

        state.setdefault("project_id", project_id_for_session(sid))
    else:
        state.setdefault("project_id", "PRJ-UNKNOWN")
    state["current_turn"] = int(state.get("current_turn", 0)) + 1

    if ticket_type not in IMPLEMENTED_TICKET_TYPES:
        ctx.route = ROUTE_STUB
        return user_input

    if state.get(STATE_VALIDATE_ACTION) or user_input.strip().startswith(
        VALIDATE_MESSAGE_PREFIX
    ):
        state[STATE_VALIDATE_ACTION] = False
        state["_va_run_validate"] = True
        ctx.route = ROUTE_VALIDATE
        logger.info("BA Router: validate → VA subgraph")
        return user_input

    if active_section == SECTION_VALIDATION:
        ctx.route = ROUTE_VALIDATE
        logger.info("BA Router: validation page → VA subgraph (discuss)")
        return user_input

    if active_section not in IMPLEMENTED_SECTIONS:
        ctx.route = ROUTE_STUB
        return user_input

    allowed, blocked_by = can_access_section(state, active_section)
    if not allowed:
        ctx.route = ROUTE_LOCKED
        state["_locked_reason"] = blocked_by
        logger.info(
            "BA Router: locked section=%s blocked_by=%s", active_section, blocked_by
        )
        return user_input

    route = SECTION_TO_ROUTE[active_section]
    ctx.route = route
    sync_sections_status_from_flags(state)
    logger.info("BA Router: section=%s route=%s", active_section, route)
    return user_input


@node(name="ba_router")
def ba_router_node(ctx: Context) -> str:
    """Route by ticket_type + active_section. Unimplemented paths go to stub/locked."""
    return route_ba_turn(ctx)
