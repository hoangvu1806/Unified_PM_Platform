"""Tool for evaluating and updating Feature Definition completion flags in state."""

from __future__ import annotations

from google.adk.tools import ToolContext

from agents.sub_graph.feature_definition.constants import (
    BLOCKER_STATUSES,
    NOT_YET_REASONABLE,
    PASS,
)
from utils import logging

logger = logging()

VALID_STATUSES = frozenset({PASS, NOT_YET_REASONABLE})


def update_feature_flag_status(
    tool_context: ToolContext,
    flag_id: str,
    status: str,
    detail: str | None = None,
) -> str:
    """Record semantic evaluation result for a Feature Definition flag after reviewing artifact data.

    You MUST call this tool for every PENDING_SEMANTIC flag in the context.

    Args:
        tool_context: ADK ToolContext providing access to session state.
        flag_id: Flag ID to evaluate, e.g., 'FD-F1' (Goal) or 'FD-F5' (Scope Conflict).
        status: Evaluation result — 'PASS' if data meets quality standards,
            or 'NOT_YET_REASONABLE' if data is insufficient or unclear.
        detail: Required when status is 'NOT_YET_REASONABLE' — explain why the data
            does not meet standards. Set to None when status is 'PASS'.

    Returns:
        Vietnamese status message with update confirmation and section completion state.
    """
    ctx_state = tool_context.state
    all_flags = dict(ctx_state.get("flags", {}))
    fd_flags = dict(all_flags.get("fd", {}))

    flag_id_clean = flag_id.strip().upper()
    status_clean = status.strip().upper()

    if status_clean not in VALID_STATUSES:
        return f"Lỗi: Trạng thái '{status}' không hợp lệ. Phải là 'PASS' hoặc 'NOT_YET_REASONABLE'."

    fd_flags[flag_id_clean] = {
        "status": status_clean,
        "detail": detail if status_clean == NOT_YET_REASONABLE else None,
    }
    all_flags["fd"] = fd_flags
    ctx_state["flags"] = all_flags

    from agents.ba_agent.section_gate import (
        section_is_complete,
        sync_sections_status_from_flags,
    )

    sync_sections_status_from_flags(ctx_state)
    completed = section_is_complete(ctx_state, "feature_definition")
    blockers = [
        f_id
        for f_id, f in fd_flags.items()
        if f.get("status") in BLOCKER_STATUSES and f_id != "FD-F4"
    ]
    logger.info(
        f"update_feature_flag_status: Updated {flag_id_clean} -> {status_clean} "
        f"(detail={detail}). Section complete={completed}"
    )

    if status_clean == PASS:
        if completed:
            return (
                f"[THÀNH CÔNG] Đã cập nhật flag '{flag_id_clean}' thành PASS. "
                f"Tất cả các flag bắt buộc đã đạt! Trạng thái phần Feature Definition: HOÀN THÀNH."
            )
        return (
            f"[THÀNH CÔNG] Đã cập nhật flag '{flag_id_clean}' thành PASS. "
            f"Trạng thái phần Feature Definition: ĐANG THỰC HIỆN. Các flag chưa hoàn thành: {', '.join(blockers)}."
        )

    # NOT_YET_REASONABLE
    reason = f" Lý do: {detail}" if detail else ""
    return (
        f"[CHƯA HỢP LÝ] Đã cập nhật flag '{flag_id_clean}' thành NOT_YET_REASONABLE.{reason} "
        f"Trạng thái phần Feature Definition: ĐANG THỰC HIỆN. Các flag chưa hoàn thành: {', '.join(blockers)}."
    )
