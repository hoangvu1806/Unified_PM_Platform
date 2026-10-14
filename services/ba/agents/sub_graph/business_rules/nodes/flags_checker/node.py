"""BR flags checker node — structured JSON, no tool calling."""

from __future__ import annotations

import json

from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from agents.sub_graph.shared.constants import PENDING_SEMANTIC
from agents.sub_graph.shared.semantic_flags import (
    SemanticFlagsEvaluation,
    apply_semantic_flag_evaluations,
    empty_evaluation_response,
)
from callbacks.inject_context import insert_context
from config.model_config import base_model

from .logic import check_br_flags_logic


async def br_flags_checker_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    flags = check_br_flags_logic(callback_context)
    pending = {
        k: v for k, v in flags.items() if v.get("status") == PENDING_SEMANTIC
    }
    if not pending:
        return empty_evaluation_response()
    rules = callback_context.state.get("artifacts", {}).get("business_rules", [])
    from agents.sub_graph.shared.context_trim import trim_feature_definition

    fd = trim_feature_definition(
        callback_context.state.get("artifacts", {}).get("feature_definition", {})
    )
    ctx = (
        f"=== FEATURE DEFINITION ===\n{json.dumps(fd, ensure_ascii=False)}\n\n"
        f"=== BUSINESS RULES ===\n{json.dumps(rules, ensure_ascii=False)}\n\n"
        f"=== PENDING FLAGS ===\n{json.dumps(pending, ensure_ascii=False)}"
    )
    insert_context(llm_request, ctx)
    return None


async def br_flags_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> None:
    text = ""
    if llm_response.content and llm_response.content.parts:
        text = llm_response.content.parts[0].text or ""
    apply_semantic_flag_evaluations(callback_context.state, "br", text)


def create_br_flags_checker_node():
    prompt_path = Path(__file__).parent / "prompt.md"
    instruction = (
        prompt_path.read_text(encoding="utf-8")
        if prompt_path.exists()
        else "Đánh giá semantic BR flags PENDING. Trả SemanticFlagsEvaluation JSON."
    )
    return LlmAgent(
        name="br_flags_checker",
        model=base_model,
        instruction=instruction,
        output_schema=SemanticFlagsEvaluation,
        before_model_callback=br_flags_checker_before_model,
        after_model_callback=br_flags_after_model,
    )
