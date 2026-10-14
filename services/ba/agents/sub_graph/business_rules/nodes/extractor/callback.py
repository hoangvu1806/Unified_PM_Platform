"""BR extractor callbacks."""

from __future__ import annotations

import json

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from agents.sub_graph.business_rules.merge import merge_business_rules
from agents.sub_graph.business_rules.schemas import BusinessRulesData
from callbacks.inject_context import insert_context
from utils.utils import parse_str_to_dict


async def br_merge_callback(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> None:
    raw = llm_response.content.parts[0].text
    parsed_dict = parse_str_to_dict(raw)
    if not parsed_dict:
        return
    try:
        parsed = BusinessRulesData.model_validate(parsed_dict)
    except Exception:
        return
    state = callback_context.state
    artifacts = dict(state.get("artifacts", {}))
    current = artifacts.get("business_rules", [])
    artifacts["business_rules"] = merge_business_rules(current, parsed)
    state["artifacts"] = artifacts


async def br_extractor_inject_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    from agents.sub_graph.shared.context_trim import trim_feature_definition

    rules = callback_context.state.get("artifacts", {}).get("business_rules", [])
    fd = trim_feature_definition(
        callback_context.state.get("artifacts", {}).get("feature_definition", {})
    )
    ctx = (
        f"=== FEATURE DEFINITION (context) ===\n"
        f"{json.dumps(fd, ensure_ascii=False)}\n\n"
        f"=== CURRENT BUSINESS RULES ===\n"
        f"{json.dumps(rules, ensure_ascii=False)}"
    )
    insert_context(llm_request, ctx)
