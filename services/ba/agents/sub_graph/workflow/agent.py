"""WF nodes — extractor, flags, discussion."""

from __future__ import annotations

import json
import re
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from agents.sub_graph.shared.constants import PENDING_SEMANTIC
from agents.sub_graph.shared.context_trim import (
    trim_business_rules,
    trim_feature_definition,
    trim_open_items,
    trim_workflow,
)
from agents.sub_graph.shared.semantic_flags import (
    SemanticFlagsEvaluation,
    empty_evaluation_response,
)
from agents.sub_graph.shared.discussion_tools import discussion_tools
from agents.sub_graph.workflow.schemas import WorkflowData
from callbacks.filter_history import create_history_filter
from callbacks.inject_context import insert_context
from config.model_config import base_model
from utils.utils import parse_str_to_dict

from google.adk.workflow import Workflow

from agents.sub_graph.workflow.nodes.flags_checker.logic import check_wf_flags_logic
from agents.ba_agent.section_gate import (
    mark_downstream_needs_review,
    record_package_change_review,
)


def _preserve_omitted_workflows(previous: str, updated: str) -> tuple[str, list[str]]:
    """Keep existing WF blocks if a model-generated replacement accidentally omits them."""
    heading = re.compile(r"(?im)^#{1,3}[^\n]*\b(WF-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+)\b[^\n]*(?:\n|$)")

    def blocks(text: str) -> dict[str, str]:
        matches = list(heading.finditer(text))
        result: dict[str, str] = {}
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            result[match.group(1).upper()] = text[match.start():end].strip()
        return result

    old_blocks = blocks(previous)
    new_blocks = blocks(updated)
    omitted = [workflow_id for workflow_id in old_blocks if workflow_id not in new_blocks]
    if omitted:
        updated = updated.rstrip() + "\n\n" + "\n\n".join(
            old_blocks[workflow_id] for workflow_id in omitted
        )
    return updated, omitted


async def wf_merge_callback(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> None:
    parsed_dict = parse_str_to_dict(llm_response.content.parts[0].text)
    if not parsed_dict:
        return
    try:
        parsed = WorkflowData.model_validate(parsed_dict)
    except Exception:
        return
    state = callback_context.state
    artifacts = dict(state.get("artifacts", {}))
    wf = dict(artifacts.get("workflow", {}))
    previous_content = str(wf.get("workflow_md_content") or "")
    preserved: list[str] = []
    content_changed = False
    if parsed.workflow_md_content and parsed.workflow_md_content.strip():
        updated_content, preserved = _preserve_omitted_workflows(
            previous_content, parsed.workflow_md_content.strip()
        )
        wf["workflow_md_content"] = updated_content
        content_changed = updated_content != previous_content
    if parsed.artifact_id:
        wf["artifact_id"] = parsed.artifact_id
    if parsed.version:
        wf["version"] = parsed.version
    if parsed.workflow_md_path:
        wf["workflow_md_path"] = parsed.workflow_md_path
    artifacts["workflow"] = wf
    state["artifacts"] = artifacts
    if content_changed:
        mark_downstream_needs_review(state, "workflow")
        state["_ba_workflow_changed_turn"] = state.get("current_turn")
        if preserved:
            state["_ba_preserved_workflows"] = preserved


async def wf_extractor_inject(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    wf = trim_workflow(callback_context.state.get("artifacts", {}).get("workflow", {}))
    br = trim_business_rules(
        callback_context.state.get("artifacts", {}).get("business_rules", [])
    )
    fd = trim_feature_definition(
        callback_context.state.get("artifacts", {}).get("feature_definition", {})
    )
    insert_context(
        llm_request,
        f"=== FEATURE DEFINITION ===\n{json.dumps(fd, ensure_ascii=False)}\n\n"
        f"=== BUSINESS RULES ===\n{json.dumps(br, ensure_ascii=False)}\n\n"
        f"=== CURRENT WORKFLOW ===\n{json.dumps(wf, ensure_ascii=False)}",
    )


async def wf_flags_before(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    flags = check_wf_flags_logic(callback_context)
    pending = {k: v for k, v in flags.items() if v.get("status") == PENDING_SEMANTIC}
    if not pending:
        return empty_evaluation_response()
    wf = trim_workflow(callback_context.state.get("artifacts", {}).get("workflow", {}))
    fd = trim_feature_definition(
        callback_context.state.get("artifacts", {}).get("feature_definition", {})
    )
    insert_context(
        llm_request,
        f"=== FEATURE DEFINITION (actors) ===\n{json.dumps(fd, ensure_ascii=False)}\n\n"
        f"=== WORKFLOW ===\n{json.dumps(wf, ensure_ascii=False)}\n\n"
        f"=== PENDING ===\n{json.dumps(pending, ensure_ascii=False)}",
    )
    return None


async def wf_flags_after(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> None:
    from agents.sub_graph.shared.semantic_flags import apply_semantic_flag_evaluations

    text = ""
    if llm_response.content and llm_response.content.parts:
        text = llm_response.content.parts[0].text or ""
    apply_semantic_flag_evaluations(callback_context.state, "wf", text)


async def wf_discussion_inject(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    from agents.sub_graph.shared.constants import (
        FAIL,
        MISSING_VALUE,
        NOT_YET_REASONABLE,
        PENDING_SEMANTIC,
        WARNING,
    )


    wf = trim_workflow(callback_context.state.get("artifacts", {}).get("workflow", {}))
    fd = trim_feature_definition(
        callback_context.state.get("artifacts", {}).get("feature_definition", {})
    )
    br = trim_business_rules(
        callback_context.state.get("artifacts", {}).get("business_rules", [])
    )
    state = callback_context.state
    if state.get("_ba_workflow_changed_turn") == state.get("current_turn"):
        if (state.get("sections_status") or {}).get("bpmn_reference") == "needs_review":
            from managers.control.bpmn import ensure_bpmn_artifact

            ensure_bpmn_artifact(state, force=True)
        record_package_change_review(state, "workflow")
        if state.get("_ba_preserved_workflows"):
            review = dict(state.get("_ba_change_review") or {})
            review["preserved_workflows"] = state["_ba_preserved_workflows"]
            state["_ba_change_review"] = review
    flags = callback_context.state.get("flags", {}).get("wf", {})
    actionable = {MISSING_VALUE, FAIL, PENDING_SEMANTIC, NOT_YET_REASONABLE, WARNING}
    checklist = [
        {
            "priority": i + 1,
            "flag_id": fid,
            "status": info.get("status"),
            "required": fid in {"WF-F1", "WF-F2", "WF-F4"},
            "message": info.get("detail") or info.get("name"),
        }
        for i, (fid, info) in enumerate(flags.items())
        if str(info.get("status", "")).upper() in actionable
    ]
    insert_context(
        llm_request,
        f"=== FEATURE DEFINITION ===\n{json.dumps(fd, ensure_ascii=False, indent=2)}\n\n"
        f"=== BUSINESS RULES ===\n{json.dumps(br, ensure_ascii=False, indent=2)}\n\n"
        f"=== WORKFLOW ===\n{json.dumps(wf, ensure_ascii=False, indent=2)}\n\n"
        f"=== CHECKLIST ===\n{json.dumps(checklist, ensure_ascii=False, indent=2)}\n\n"
        f"=== PACKAGE CHANGE REVIEW (deterministic checks; source of truth) ===\n{json.dumps(callback_context.state.get('_ba_change_review') or {}, ensure_ascii=False, indent=2)}\n\n"
        f"=== OPEN QUESTIONS ===\n{json.dumps(trim_open_items(callback_context.state.get('open_questions', [])), ensure_ascii=False)}\n\n"
        f"=== ASSUMPTIONS ===\n{json.dumps(trim_open_items(callback_context.state.get('assumptions', [])), ensure_ascii=False)}",
    )


async def wf_change_review_after(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> None:
    """Append an authoritative, deterministic package review to the chat reply."""
    review = callback_context.state.get("_ba_change_review") or {}
    if (
        review.get("edited_section") != "workflow"
        or review.get("turn") != callback_context.state.get("current_turn")
        or not llm_response.content
        or not llm_response.content.parts
    ):
        return

    failed = review.get("failed_checks") or []
    warnings = review.get("warnings") or []
    lines = ["\n\n**Rà soát package sau khi sửa Workflow:**"]
    if failed:
        lines.append("Còn lỗi cần xử lý; chưa nên bấm Validate:")
        for finding in failed:
            lines.append(
                f"- **{finding.get('check_id', '')} {finding.get('name', '')}:** "
                f"{finding.get('detail', '')}"
            )
            if finding.get("suggestion"):
                lines.append(f"  Gợi ý: {finding['suggestion']}")
    else:
        lines.append(
            "Rà soát nhất quán giữa các artifact BA không thấy lỗi chặn. "
            "Package sẵn sàng để bạn chạy Validate; đây chưa phải kết quả Validate chính thức."
        )
    if warnings:
        lines.append("Cảnh báo cần lưu ý:")
        for finding in warnings:
            lines.append(
                f"- **{finding.get('check_id', '')} {finding.get('name', '')}:** "
                f"{finding.get('detail', '')}"
            )
    preserved = review.get("preserved_workflows") or []
    if preserved:
        lines.append(
            "Các workflow khác được giữ nguyên trong artifact: "
            + ", ".join(f"`{item}`" for item in preserved)
            + "."
        )
    llm_response.content.parts[0].text = (
        (llm_response.content.parts[0].text or "") + "\n".join(lines)
    )


_wf_prompt = (
    Path(__file__).resolve().parent / "nodes/flags_checker/prompt.md"
)
_wf_flags_instruction = (
    _wf_prompt.read_text(encoding="utf-8")
    if _wf_prompt.exists()
    else "Đánh giá WF-F2/WF-F4. Trả SemanticFlagsEvaluation JSON. KHÔNG gọi tool."
)

_wf_extractor = LlmAgent(
    name="wf_extractor",
    model=base_model,
    instruction=(
        "Trích xuất/cập nhật workflow markdown NGẮN GỌN cho **một** luồng/story tại một thời điểm. "
        "Artifact workflow có thể chứa NHIỀU workflow. Khi sửa một WF-ID, phải giữ nguyên đầy đủ mọi WF-ID khác và mọi bước/BR Ref hiện có; không được thay toàn bộ artifact bằng riêng luồng đang sửa. Trả lại toàn bộ nội dung workflow sau khi merge. "
        "Main Flow và Exception Flows dùng bảng cột: "
        "`Step | Actor | Action | BR | Gateway` "
        "(Gateway = XOR hoặc AND hoặc để trống). "
        "Actors phải khớp FD actors (sẽ thành lanes). "
        "Main Flow ≥3 bước, Exception Flows, End States. "
        "Không lặp lại toàn bộ BR — chỉ tham chiếu BR-XX."
    ),
    output_schema=WorkflowData,
    before_model_callback=[
        create_history_filter(
            visible_authors=["wf_discussion"],
            process_latest_message_only=True,
        ),
        wf_extractor_inject,
    ],
    after_model_callback=wf_merge_callback,
)

_wf_flags = LlmAgent(
    name="wf_flags_checker",
    model=base_model,
    instruction=_wf_flags_instruction,
    output_schema=SemanticFlagsEvaluation,
    before_model_callback=wf_flags_before,
    after_model_callback=wf_flags_after,
)

_wf_discussion = LlmAgent(
    name="wf_discussion",
    model=base_model,
    instruction=(
        "Bạn là BA Agent section Workflow. "
        "Xác nhận Main Flow / Exception / End States cho **một** luồng tại một thời điểm. "
        "Bảng bước dùng cột `Step | Actor | Action | BR | Gateway` "
        "với Gateway XOR (nhánh độc quyền) hoặc AND (song song) hoặc để trống. "
        "Actors phải khớp Feature Definition (không invent Management/Supplier). "
        "Hỏi làm rõ theo CHECKLIST (ưu tiên required=true). "
        "Không dùng mã flag kỹ thuật (WF-F1…) trong câu trả lời User. "
        "Nhắc OQ/Assumptions nếu có. "
        "After every Workflow change, read PACKAGE CHANGE REVIEW (deterministic checks) and review all existing workflows, BR references, User Stories, BPMN, and UI Touchpoints. Report concrete findings and affected sections. If failed_checks is non-empty, do not claim the package is okay and do not ask the user to Validate; guide them to fix the listed findings. Only when failed_checks is empty may you say the package is ready for the user to run Validate. Never claim that Validate has already run. "
        "You have tools: wiki first (`wiki.search_pages` / `wiki.fetch_page`); "
        "do NOT `web_search` for FD scope_out / non-goals / unrelated browsing; "
        "`web_search` only after wiki miss for in-package clarification; "
        "`preview_bpmn` after actor-step rows. Never approve/ingest/propose wiki."
    ),
    tools=discussion_tools(include_preview_bpmn=True),
    before_model_callback=[
        create_history_filter(visible_authors=["wf_discussion"], max_turns=3),
        wf_discussion_inject,
    ],
    after_model_callback=wf_change_review_after,
)

# WF: skip OQ detector (already captured in FD) — 3 LLM calls not 4.
wf_subgraph = Workflow(
    name="workflow_workflow",
    edges=[
        ("START", _wf_extractor),
        (_wf_extractor, _wf_flags),
        (_wf_flags, _wf_discussion),
    ],
)
