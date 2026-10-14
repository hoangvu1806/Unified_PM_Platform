"""User Stories (section id ``use_cases``) subgraph."""

from __future__ import annotations

import json
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.workflow import Workflow

from agents.sub_graph.shared.constants import PENDING_SEMANTIC
from agents.sub_graph.shared.discussion_tools import discussion_tools
from agents.sub_graph.shared.semantic_flags import (
    SemanticFlagsEvaluation,
    apply_semantic_flag_evaluations,
    empty_evaluation_response,
)
from agents.sub_graph.shared.wiki_context import format_approved_wiki_context
from agents.sub_graph.use_cases.merge import (
    check_uc_flags_logic,
    is_user_story_row_complete,
    merge_use_cases,
    resolve_active_user_story_id,
)
from agents.sub_graph.use_cases.schemas import UseCasesData
from callbacks.filter_history import create_history_filter
from callbacks.inject_context import insert_context
from config.model_config import base_model
from utils.utils import parse_str_to_dict


async def uc_merge(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> None:
    parsed_dict = parse_str_to_dict(llm_response.content.parts[0].text)
    if not parsed_dict:
        return
    try:
        parsed = UseCasesData.model_validate(parsed_dict)
    except Exception:
        return
    artifacts = dict(callback_context.state.get("artifacts", {}))
    current = artifacts.get("use_cases", [])
    active = callback_context.state.get("active_user_story_id")
    merged, new_active = merge_use_cases(
        current, parsed, active_user_story_id=active
    )
    artifacts["use_cases"] = merged
    callback_context.state["artifacts"] = artifacts
    callback_context.state["active_user_story_id"] = new_active


async def uc_extractor_inject(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    cases = callback_context.state.get("artifacts", {}).get("use_cases", [])
    wf = callback_context.state.get("artifacts", {}).get("workflow", {})
    fd = callback_context.state.get("artifacts", {}).get("feature_definition", {})
    br = callback_context.state.get("artifacts", {}).get("business_rules", [])
    active = resolve_active_user_story_id(
        cases if isinstance(cases, list) else [],
        callback_context.state.get("active_user_story_id"),
    )
    active_row = next(
        (c for c in (cases or []) if isinstance(c, dict) and c.get("id") == active),
        None,
    )
    lock_note = {
        "active_user_story_id": active,
        "active_complete": is_user_story_row_complete(active_row),
        "rule": (
            "Extract / update ONLY the active User Story this turn. "
            "Do not invent a second US-xx until the active story has statement + AC "
            "and the PO says it is done."
        ),
    }
    insert_context(
        llm_request,
        f"=== FEATURE DEFINITION ===\n{json.dumps(fd, ensure_ascii=False)}\n\n"
        f"=== BUSINESS RULES ===\n{json.dumps(br, ensure_ascii=False)}\n\n"
        f"=== WORKFLOW ===\n{json.dumps(wf, ensure_ascii=False)}\n\n"
        f"=== USER STORIES (use_cases) ===\n{json.dumps(cases, ensure_ascii=False)}\n\n"
        f"=== ACTIVE STORY LOCK ===\n{json.dumps(lock_note, ensure_ascii=False)}",
    )


async def uc_flags_before(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    flags = check_uc_flags_logic(callback_context)
    pending = {k: v for k, v in flags.items() if v.get("status") == PENDING_SEMANTIC}
    if not pending:
        return empty_evaluation_response()
    cases = callback_context.state.get("artifacts", {}).get("use_cases", [])
    fd = callback_context.state.get("artifacts", {}).get("feature_definition", {})
    br = callback_context.state.get("artifacts", {}).get("business_rules", [])
    insert_context(
        llm_request,
        f"=== FEATURE DEFINITION ===\n{json.dumps(fd, ensure_ascii=False)}\n\n"
        f"=== BUSINESS RULES ===\n{json.dumps(br, ensure_ascii=False)}\n\n"
        f"=== USER STORIES ===\n{json.dumps(cases, ensure_ascii=False)}\n\n"
        f"=== PENDING ===\n{json.dumps(pending, ensure_ascii=False)}",
    )
    return None


async def uc_flags_after(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> None:
    text = ""
    if llm_response.content and llm_response.content.parts:
        text = llm_response.content.parts[0].text or ""
    apply_semantic_flag_evaluations(callback_context.state, "uc", text)


async def uc_discussion_inject(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    from agents.sub_graph.shared.constants import (
        FAIL,
        MISSING_VALUE,
        NOT_YET_REASONABLE,
        PENDING_SEMANTIC,
        WARNING,
    )

    cases = callback_context.state.get("artifacts", {}).get("use_cases", [])
    fd = callback_context.state.get("artifacts", {}).get("feature_definition", {})
    br = callback_context.state.get("artifacts", {}).get("business_rules", [])
    flags = callback_context.state.get("flags", {}).get("uc", {})
    active = resolve_active_user_story_id(
        cases if isinstance(cases, list) else [],
        callback_context.state.get("active_user_story_id"),
    )
    active_row = next(
        (c for c in (cases or []) if isinstance(c, dict) and c.get("id") == active),
        None,
    )
    actionable = {MISSING_VALUE, FAIL, PENDING_SEMANTIC, NOT_YET_REASONABLE, WARNING}
    checklist = [
        {
            "priority": i + 1,
            "flag_id": fid,
            "status": info.get("status"),
            "required": fid
            in {"UC-F1", "UC-F2", "UC-F3", "UC-F5", "UC-F7", "UC-F8"},
            "message": info.get("detail") or info.get("name"),
        }
        for i, (fid, info) in enumerate(flags.items())
        if str(info.get("status", "")).upper() in actionable
    ]
    wiki_block = format_approved_wiki_context(callback_context.state)
    insert_context(
        llm_request,
        f"{wiki_block}\n"
        f"=== FEATURE DEFINITION ===\n{json.dumps(fd, ensure_ascii=False, indent=2)}\n\n"
        f"=== BUSINESS RULES ===\n{json.dumps(br, ensure_ascii=False, indent=2)}\n\n"
        f"=== USER STORIES (use_cases) ===\n{json.dumps(cases, ensure_ascii=False, indent=2)}\n\n"
        f"=== ACTIVE USER STORY ===\n{json.dumps({'id': active, 'complete': is_user_story_row_complete(active_row), 'row': active_row}, ensure_ascii=False, indent=2)}\n\n"
        f"=== CHECKLIST ===\n{json.dumps(checklist, ensure_ascii=False, indent=2)}\n\n"
        f"=== OPEN QUESTIONS ===\n{json.dumps(callback_context.state.get('open_questions', []), ensure_ascii=False)}\n\n"
        f"=== ASSUMPTIONS ===\n{json.dumps(callback_context.state.get('assumptions', []), ensure_ascii=False)}",
    )


_uc_prompt = Path(__file__).resolve().parent / "nodes/flags_checker/prompt.md"
_uc_flags_instruction = (
    _uc_prompt.read_text(encoding="utf-8")
    if _uc_prompt.exists()
    else "Đánh giá UC-F5/UC-F8. Trả SemanticFlagsEvaluation JSON. KHÔNG gọi tool."
)

_uc_extractor = LlmAgent(
    name="uc_extractor",
    model=base_model,
    instruction=(
        "Trích xuất User Stories (user story + acceptance criteria). "
        "MỖI LƯỢT chỉ 1 story (active_user_story_id). "
        "statement: 'Là ..., tôi muốn ... để ...'. "
        "Một actor, một goal; AC cite BR-XX đã có. "
        "actor_id phải khớp ACT-ID từ Feature Definition. "
        "KHÔNG invent US thứ hai cho đến khi story đang active đủ statement+AC "
        "và PO xác nhận xong. Không ghi đè artifact từ wiki."
    ),
    output_schema=UseCasesData,
    before_model_callback=[
        create_history_filter(visible_authors=["uc_discussion"], max_turns=5),
        uc_extractor_inject,
    ],
    after_model_callback=uc_merge,
)

_uc_flags = LlmAgent(
    name="uc_flags_checker",
    model=base_model,
    instruction=_uc_flags_instruction,
    output_schema=SemanticFlagsEvaluation,
    before_model_callback=uc_flags_before,
    after_model_callback=uc_flags_after,
)

_uc_discussion = LlmAgent(
    name="uc_discussion",
    model=base_model,
    instruction=(
        "Bạn là BA Agent section **User Stories** (id nội bộ vẫn use_cases). "
        "Acknowledge APPROVED WIKI trước; chỉ brainstorm ý MỚI cùng topic — "
        "không auto-overwrite artifacts từ wiki; agents không approve wiki. "
        "Làm việc trên **một** active User Story mỗi lúc (xem ACTIVE USER STORY). "
        "Xác nhận statement + AC theo CHECKLIST (ưu tiên required=true). "
        "Không dùng mã flag (UC-F1…) với User. Nhắc OQ/Assumptions nếu có. "
        "Khi story active đủ và PO nói xong, mới mở US tiếp theo. "
        "Không yêu cầu N stories để Validate — tối thiểu 1 là đủ. "
        "You have tools: `wiki.search_pages` / `wiki.fetch_page` before inventing; "
        "do NOT `web_search` for FD scope_out / non-goals / unrelated browsing; "
        "`web_search` only after wiki miss for in-package clarification "
        "(if not configured, say so — do not hallucinate); "
        "`preview_bpmn` after WF has actor-step rows. Never approve/ingest/propose."
    ),
    tools=discussion_tools(include_preview_bpmn=True),
    before_model_callback=[
        create_history_filter(visible_authors=["uc_discussion"], max_turns=5),
        uc_discussion_inject,
    ],
)

uc_subgraph = Workflow(
    name="use_cases_workflow",
    edges=[
        ("START", _uc_extractor),
        (_uc_extractor, _uc_flags),
        (_uc_flags, _uc_discussion),
    ],
)
