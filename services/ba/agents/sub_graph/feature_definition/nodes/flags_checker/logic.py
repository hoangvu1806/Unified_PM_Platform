"""Evaluation logic for Feature Definition completion flags.

Pure logic functions that compute flag statuses from artifact data.
Used by both the before_model_callback (LlmAgent) and tests.
"""

from __future__ import annotations

from typing import Any

from agents.sub_graph.feature_definition.constants import (
    FAIL,
    MISSING_VALUE,
    NOT_YET_REASONABLE,
    PASS,
    PENDING_SEMANTIC,
    WARNING,
)
from utils import logging

logger = logging()


def check_fd_flags_logic(ctx) -> dict[str, Any]:
    """Evaluate 5 completion flags for Feature Definition artifacts.

    Accepts either an ADK Context or CallbackContext (both have `.state`).

    Priority: FD-F1 > FD-F2 > FD-F3 > FD-F5 > FD-F4

    Status flow:
        MISSING_VALUE → data provided → FAIL or PENDING_SEMANTIC or PASS
        FAIL → data added → PENDING_SEMANTIC or PASS
        PENDING_SEMANTIC → agent evaluates → PASS or NOT_YET_REASONABLE
        NOT_YET_REASONABLE → next turn reset → PENDING_SEMANTIC (re-evaluate)
        PASS → preserved
    """
    fd = ctx.state.get("artifacts", {}).get("feature_definition", {})
    logger.info(f"check_fd_flags_logic: [ARTIFACT STATE] FD Artifact = {fd}")

    existing_flags = dict(ctx.state.get("flags", {}).get("fd", {}))
    flags: dict[str, dict[str, Any]] = {}

    # P1: FD-F1 Goal — semantic flag
    goal = fd.get("goal", "")
    if not goal or not str(goal).strip():
        flags["FD-F1"] = _flag(
            1,
            "Mục tiêu tính năng (Goal)",
            MISSING_VALUE,
            "Mục tiêu & lý do tồn tại của tính năng (WHY) chưa được khai báo.",
        )
    elif _was_passed(existing_flags, "FD-F1"):
        flags["FD-F1"] = _flag(1, "Mục tiêu tính năng (Goal)", PASS)
    else:
        flags["FD-F1"] = _flag(
            1,
            "Mục tiêu tính năng (Goal)",
            PENDING_SEMANTIC,
            "Cần xác nhận mục tiêu & giá trị của tính năng.",
        )

    # P2: FD-F2 Actors >= 2 — logic flag
    actors = fd.get("actors", [])
    actors_len = len(actors) if isinstance(actors, list) else 0
    if actors_len == 0:
        flags["FD-F2"] = _flag(
            2,
            "Đối tượng sử dụng & Hệ thống (Actors)",
            MISSING_VALUE,
            "Chưa khai báo đối tượng sử dụng hoặc hệ thống liên quan.",
        )
    elif actors_len >= 2:
        flags["FD-F2"] = _flag(2, "Đối tượng sử dụng & Hệ thống (Actors)", PASS)
    else:
        flags["FD-F2"] = _flag(
            2,
            "Đối tượng sử dụng & Hệ thống (Actors)",
            FAIL,
            f"Cần ít nhất 2 đối tượng/hệ thống, hiện có {actors_len}.",
        )

    # P3: FD-F3 Scope In >= 1 — logic flag
    scope_in = fd.get("scope_in", [])
    scope_in_len = len(scope_in) if isinstance(scope_in, list) else 0
    if scope_in_len == 0:
        flags["FD-F3"] = _flag(
            3,
            "Phạm vi thực hiện (Scope In)",
            MISSING_VALUE,
            "Chưa khai báo tính năng trong phạm vi.",
        )
    else:
        flags["FD-F3"] = _flag(3, "Phạm vi thực hiện (Scope In)", PASS)

    # P4: FD-F5 Scope Conflict — semantic flag
    scope_out = fd.get("scope_out", [])
    has_both_scopes = (
        isinstance(scope_in, list)
        and scope_in
        and isinstance(scope_out, list)
        and scope_out
    )
    if not has_both_scopes:
        flags["FD-F5"] = _flag(
            4, "Kiểm tra mâu thuẫn phạm vi", PASS, "Chưa đủ dữ liệu để mâu thuẫn."
        )
    elif _was_passed(existing_flags, "FD-F5"):
        flags["FD-F5"] = _flag(4, "Kiểm tra mâu thuẫn phạm vi", PASS)
    else:
        flags["FD-F5"] = _flag(
            4,
            "Kiểm tra mâu thuẫn phạm vi",
            PENDING_SEMANTIC,
            "Cần kiểm tra mâu thuẫn giữa Scope In và Scope Out.",
        )

    # P5: FD-F4 Scope Out >= 1 — warning flag (non-blocking)
    scope_out_len = len(scope_out) if isinstance(scope_out, list) else 0
    if scope_out_len >= 1:
        flags["FD-F4"] = _flag(5, "Phạm vi loại trừ (Scope Out)", PASS)
    else:
        flags["FD-F4"] = _flag(
            5,
            "Phạm vi loại trừ (Scope Out)",
            WARNING,
            "Khuyến nghị khai báo để tránh scope creep.",
        )

    # Auto-reset NOT_YET_REASONABLE → PENDING_SEMANTIC
    for f_id, f_info in flags.items():
        old = existing_flags.get(f_id, {})
        if (
            old.get("status") == NOT_YET_REASONABLE
            and f_info["status"] == PENDING_SEMANTIC
        ):
            logger.info(
                f"check_fd_flags_logic: Reset {f_id} from NOT_YET_REASONABLE → PENDING_SEMANTIC"
            )

    all_flags = dict(ctx.state.get("flags", {}))
    all_flags["fd"] = flags
    ctx.state["flags"] = all_flags

    from agents.ba_agent.section_gate import sync_sections_status_from_flags

    sync_sections_status_from_flags(ctx.state)
    logger.info(f"fd_flags_checker_node: Evaluated flags={flags}")
    return flags


def _flag(
    priority: int, name: str, status: str, detail: str | None = None
) -> dict[str, Any]:
    """Build a flag dict."""
    return {"priority": priority, "name": name, "status": status, "detail": detail}


def _was_passed(existing_flags: dict, flag_id: str) -> bool:
    """Check if a flag was previously evaluated as PASS."""
    return existing_flags.get(flag_id, {}).get("status") == PASS
