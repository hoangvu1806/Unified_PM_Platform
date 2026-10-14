"""Callbacks for Feature Definition Discussion Node."""

from __future__ import annotations

import json
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest

from agents.sub_graph.feature_definition.constants import (
    FAIL,
    MISSING_VALUE,
    NOT_YET_REASONABLE,
    PENDING_SEMANTIC,
)
from callbacks.inject_context import insert_context
from agents.sub_graph.shared.wiki_context import format_approved_wiki_context
from utils import logging

logger = logging()

# Priority rules: (flag_id, field_name, is_required, default_message)
PRIORITY_RULES = (
    (
        "FD-F1",
        "goal",
        True,
        "Mục tiêu & lý do tồn tại của tính năng (WHY) chưa được khai báo hoặc chưa thể hiện rõ giá trị mang lại.",
    ),
    (
        "FD-F2",
        "actors",
        True,
        "Cần khai báo ít nhất 2 tác nhân liên quan (bao gồm vai trò người dùng và các hệ thống tích hợp bên ngoài).",
    ),
    (
        "FD-F3",
        "scope_in",
        True,
        "Chưa liệt kê các chức năng/khả năng chính thuộc phạm vi thực hiện (Scope In).",
    ),
    (
        "FD-F5",
        "conflict",
        True,
        "Phát hiện mâu thuẫn phạm vi: có chức năng vừa xuất hiện trong Scope In vừa xuất hiện trong Scope Out.",
    ),
    (
        "FD-F4",
        "scope_out",
        False,
        "Nên bổ sung các chức năng không thực hiện (Scope Out) để tránh scope creep.",
    ),
)


def get_fd_checklist(flags: dict[str, Any]) -> list[dict[str, Any]]:
    """Compute checklist of non-PASS flags for discussion agent context.

    No `execute` field — discussion agent doesn't call tools.
    """
    actionable_statuses = {MISSING_VALUE, FAIL, PENDING_SEMANTIC, NOT_YET_REASONABLE}
    checklist = []

    for flag_id, field_name, is_req, default_msg in PRIORITY_RULES:
        f_info = flags.get(flag_id, {})
        status = str(f_info.get("status") or "").upper()
        if status not in actionable_statuses:
            continue

        msg = f_info.get("detail") or default_msg
        checklist.append(
            {
                "priority": len(checklist) + 1,
                "status": status,
                "field": field_name,
                "required": is_req,
                "message": msg,
            }
        )

    return checklist


async def fd_discussion_inject_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> None:
    """Inject Artifact state, Checklist, OQ and ASM into LLM Request."""
    state = callback_context.state
    artifacts = state.get("artifacts", {}).get("feature_definition", {})
    flags = state.get("flags", {}).get("fd", {})
    oqs = state.get("open_questions", [])
    asms = state.get("assumptions", [])
    checklist = get_fd_checklist(flags)

    current_artifact_data = {
        "goal": artifacts.get("goal") or "",
        "actors": artifacts.get("actors") or [],
        "scope_in": artifacts.get("scope_in") or [],
        "scope_out": artifacts.get("scope_out") or [],
    }

    context_blocks = [
        format_approved_wiki_context(state),
        f"=== CURRENT ARTIFACT DATA ===\n{json.dumps(current_artifact_data, ensure_ascii=False, indent=2)}",
        f"=== CHECKLIST ===\n{json.dumps(checklist, ensure_ascii=False, indent=2)}",
        f"=== OPEN QUESTIONS ===\n{json.dumps(oqs, ensure_ascii=False, indent=2)}",
        f"=== ASSUMPTIONS ===\n{json.dumps(asms, ensure_ascii=False, indent=2)}",
    ]

    context_prompt = "\n\n".join(context_blocks)

    insert_context(llm_request, context_prompt)
    logger.info(
        f"fd_discussion_inject_callback: [ARTIFACT STATE] FD Artifact = {current_artifact_data} | "
        f"CHECKLIST (count={len(checklist)}), OPEN QUESTIONS (count={len(oqs)}), ASSUMPTIONS (count={len(asms)})"
    )
