"""Tool to update BR semantic flags."""

from __future__ import annotations

from google.adk.tools import ToolContext

from agents.ba_agent.section_gate import sync_sections_status_from_flags
from agents.sub_graph.shared.constants import NOT_YET_REASONABLE, PASS

VALID = frozenset({PASS, NOT_YET_REASONABLE})


def update_br_flag_status(
    tool_context: ToolContext,
    flag_id: str,
    status: str,
    detail: str | None = None,
) -> str:
    all_flags = dict(tool_context.state.get("flags", {}))
    br_flags = dict(all_flags.get("br", {}))
    status_clean = status.strip().upper()
    if status_clean not in VALID:
        return "Status phải là PASS hoặc NOT_YET_REASONABLE."
    fid = flag_id.strip().upper()
    br_flags[fid] = {
        "status": status_clean,
        "detail": detail if status_clean == NOT_YET_REASONABLE else None,
    }
    all_flags["br"] = br_flags
    tool_context.state["flags"] = all_flags
    sync_sections_status_from_flags(tool_context.state)
    return f"Đã cập nhật {fid} → {status_clean}."
