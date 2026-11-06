"""Callbacks for Feature Definition Discussion Node."""

from __future__ import annotations

import json
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

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
        f"=== OQ ARTIFACT SYNC RESULT ===\n{json.dumps(state.get('_oq_sync_result') or {}, ensure_ascii=False, indent=2)}",
    ]

    context_prompt = "\n\n".join(context_blocks)

    insert_context(llm_request, context_prompt)
    logger.info(
        f"fd_discussion_inject_callback: [ARTIFACT STATE] FD Artifact = {current_artifact_data} | "
        f"CHECKLIST (count={len(checklist)}), OPEN QUESTIONS (count={len(oqs)}), ASSUMPTIONS (count={len(asms)})"
    )


async def oq_sync_report_after(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> None:
    """Report the actual OQ artifact synchronization result, not a model claim."""
    result = callback_context.state.get("_oq_sync_result") or {}
    if (
        result.get("turn") != callback_context.state.get("current_turn")
        or not llm_response.content
        or not llm_response.content.parts
    ):
        return
    pending = result.get("pending_oq_ids") or []
    lines = ["\n\n**Đồng bộ sau khi chốt Open Question:**"]
    if pending:
        lines.append(
            "Chưa đồng bộ xong các phần liên quan cho "
            + ", ".join(f"`{item}`" for item in pending)
            + "; chưa nên Validate. Cần làm rõ hoặc hoàn tất các cập nhật bên dưới."
        )
        oq_by_id = {
            str(item.get("id") or "").upper(): item
            for item in callback_context.state.get("open_questions") or []
        }
        for oq_id in pending:
            refs = oq_by_id.get(str(oq_id).upper(), {}).get("affected_artifacts") or []
            if refs:
                ref_ids = [
                    ref.get("artifact_id") if isinstance(ref, dict) else getattr(ref, "artifact_id", "")
                    for ref in refs
                ]
                lines.append(f"- `{oq_id}` cần đồng bộ: " + ", ".join(f"`{item}`" for item in ref_ids if item))
    else:
        updated = result.get("updated_artifacts") or []
        if updated:
            lines.append("Đã cập nhật: " + ", ".join(f"`{item}`" for item in updated) + ".")
        else:
            lines.append("Đã rà artifact liên quan; không cần sửa artifact nào theo câu trả lời này.")
        review = result.get("review") or {}
        failed = review.get("failed_checks") or []
        if failed:
            lines.append("Rà soát package còn lỗi; chưa nên Validate:")
            for finding in failed:
                lines.append(
                    f"- **{finding.get('check_id', '')} {finding.get('name', '')}:** "
                    f"{finding.get('detail', '')}"
                )
        else:
            lines.append(
                "Rà soát package không thấy lỗi chặn; bạn có thể chạy Validate chính thức. "
                "Đây chưa phải kết quả Validate."
            )
    for error in result.get("errors") or []:
        lines.append(f"- {error}")
    review = result.get("review") or {}
    if pending:
        for finding in review.get("failed_checks") or []:
            lines.append(
                f"- **{finding.get('check_id', '')} {finding.get('name', '')}:** "
                f"{finding.get('detail', '')}"
            )
    for warning in review.get("warnings") or []:
        lines.append(
            f"- Cảnh báo {warning.get('check_id', '')} {warning.get('name', '')}: "
            f"{warning.get('detail', '')}"
        )
    llm_response.content.parts[0].text = (
        (llm_response.content.parts[0].text or "") + "\n".join(lines)
    )
