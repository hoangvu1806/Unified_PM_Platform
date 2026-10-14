"""Shared FunctionNodes for the unified BA graph."""

from __future__ import annotations

from google.adk import Context
from google.adk.workflow import node

from agents.ba_agent.constants import (
    SECTION_LABELS,
    STATE_ACTIVE_SECTION,
    STATE_TICKET_TYPE,
    TICKET_LABELS,
)


@node(name="ba_not_ready")
def ba_not_ready_node(ctx: Context) -> str:
    """Tell the user this ticket type or section is not on the live graph yet."""
    state = ctx.state
    ticket_type = state.get(STATE_TICKET_TYPE, "")
    active_section = state.get(STATE_ACTIVE_SECTION, "")
    ticket_label = TICKET_LABELS.get(ticket_type, ticket_type or "unknown")
    section_label = SECTION_LABELS.get(active_section, active_section or "unknown")

    return (
        f"BA Agent đang chạy một graph thống nhất. "
        f"Ticket `{ticket_label}` / section `{section_label}` chưa có subgraph trên graph này. "
        "Hiện tại chỉ New Feature với FD → BR → WF → UC được triển khai."
    )


@node(name="ba_section_locked")
def ba_section_locked_node(ctx: Context) -> str:
    """Sequential gate — prior section blockers must pass first."""
    state = ctx.state
    active_section = state.get(STATE_ACTIVE_SECTION, "")
    blocked_by = state.get("_locked_reason", "feature_definition")
    prior_label = SECTION_LABELS.get(blocked_by, blocked_by)
    current_label = SECTION_LABELS.get(active_section, active_section)

    return (
        f"Section **{current_label}** chưa mở. "
        f"Cần hoàn thành các blocker flags ở **{prior_label}** trước (thứ tự FD → BR → WF → UC)."
    )
