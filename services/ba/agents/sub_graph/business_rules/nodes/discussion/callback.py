"""BR discussion callbacks — FD-style checklist + trimmed upstream FD context."""

from __future__ import annotations

import json

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest

from agents.sub_graph.shared.constants import (
    FAIL,
    MISSING_VALUE,
    NOT_YET_REASONABLE,
    PENDING_SEMANTIC,
    WARNING,
)
from agents.sub_graph.shared.context_trim import (
    trim_feature_definition,
    trim_open_items,
)
from callbacks.inject_context import insert_context

PRIORITY_RULES = (
    ("BR-F1", "business_rules", True, "Cần ít nhất 2 business rules."),
    ("BR-F4", "contradiction", True, "Các BR không được mâu thuẫn nhau."),
    ("BR-F2", "source", False, "Nên khai báo source cho mọi rule."),
    ("BR-F3", "measurable", False, "Mỗi rule nên có trigger + outcome đo được."),
    ("BR-F5", "true_br", False, "Tránh lẫn technical constraint vào BR."),
)


def get_br_checklist(flags: dict) -> list[dict]:
    actionable = {MISSING_VALUE, FAIL, PENDING_SEMANTIC, NOT_YET_REASONABLE, WARNING}
    checklist = []
    for flag_id, field, required, default_msg in PRIORITY_RULES:
        info = flags.get(flag_id, {})
        status = str(info.get("status") or "").upper()
        if status not in actionable or status == "PASS":
            continue
        checklist.append(
            {
                "priority": len(checklist) + 1,
                "status": status,
                "field": field,
                "required": required,
                "message": info.get("detail") or default_msg,
            }
        )
    return checklist


async def br_discussion_inject_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    state = callback_context.state
    rules = state.get("artifacts", {}).get("business_rules", [])
    fd = trim_feature_definition(state.get("artifacts", {}).get("feature_definition", {}))
    flags = state.get("flags", {}).get("br", {})
    checklist = get_br_checklist(flags)
    ctx = (
        f"=== FEATURE DEFINITION ===\n{json.dumps(fd, ensure_ascii=False)}\n\n"
        f"=== BUSINESS RULES ===\n{json.dumps(rules, ensure_ascii=False)}\n\n"
        f"=== CHECKLIST ===\n{json.dumps(checklist, ensure_ascii=False)}\n\n"
        f"=== OPEN QUESTIONS ===\n"
        f"{json.dumps(trim_open_items(state.get('open_questions', [])), ensure_ascii=False)}\n\n"
        f"=== ASSUMPTIONS ===\n"
        f"{json.dumps(trim_open_items(state.get('assumptions', [])), ensure_ascii=False)}"
    )
    insert_context(llm_request, ctx)
