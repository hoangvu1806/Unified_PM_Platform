"""WF nodes — extractor, flags, discussion."""

from __future__ import annotations

import json
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
    artifacts = dict(callback_context.state.get("artifacts", {}))
    wf = dict(artifacts.get("workflow", {}))
    if parsed.workflow_md_content and parsed.workflow_md_content.strip():
        wf["workflow_md_content"] = parsed.workflow_md_content.strip()
    if parsed.artifact_id:
        wf["artifact_id"] = parsed.artifact_id
    if parsed.version:
        wf["version"] = parsed.version
    if parsed.workflow_md_path:
        wf["workflow_md_path"] = parsed.workflow_md_path
    artifacts["workflow"] = wf
    callback_context.state["artifacts"] = artifacts


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
        f"=== OPEN QUESTIONS ===\n{json.dumps(trim_open_items(callback_context.state.get('open_questions', [])), ensure_ascii=False)}\n\n"
        f"=== ASSUMPTIONS ===\n{json.dumps(trim_open_items(callback_context.state.get('assumptions', [])), ensure_ascii=False)}",
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
