"""Callbacks for Feature Definition Flags Checker Node.

before_model_callback pattern:
1. Run logic check (check_fd_flags_logic) to evaluate all flags
2. If no PENDING_SEMANTIC flags → return empty SemanticFlagsEvaluation JSON
3. If PENDING_SEMANTIC exists → inject context, let LLM evaluate
"""

from __future__ import annotations

import json

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from agents.sub_graph.shared.constants import PENDING_SEMANTIC
from agents.sub_graph.shared.semantic_flags import empty_evaluation_response
from callbacks.inject_context import insert_context
from utils import logging

from .logic import check_fd_flags_logic

logger = logging()


async def fd_flags_checker_before_model(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None:
    """Run logic checks and early-stop if no semantic evaluation is needed."""
    flags = check_fd_flags_logic(callback_context)

    pending = {
        f_id: f_info
        for f_id, f_info in flags.items()
        if f_info.get("status") == PENDING_SEMANTIC
    }

    if not pending:
        logger.info(
            "fd_flags_checker_before_model: No PENDING_SEMANTIC flags — skipping LLM."
        )
        return empty_evaluation_response()

    artifact_data = callback_context.state.get("artifacts", {}).get(
        "feature_definition", {}
    )
    current_data = {
        "goal": artifact_data.get("goal") or "",
        "actors": artifact_data.get("actors") or [],
        "scope_in": artifact_data.get("scope_in") or [],
        "scope_out": artifact_data.get("scope_out") or [],
    }

    pending_list = [{"flag_id": f_id, **f_info} for f_id, f_info in pending.items()]

    context_text = (
        f"=== ARTIFACT DATA ===\n{json.dumps(current_data, ensure_ascii=False, indent=2)}\n\n"
        f"=== PENDING SEMANTIC FLAGS ===\n{json.dumps(pending_list, ensure_ascii=False, indent=2)}"
    )

    insert_context(llm_request, context_text)
    logger.info(
        f"fd_flags_checker_before_model: {len(pending)} PENDING_SEMANTIC flags → calling LLM. "
        f"Flags: {list(pending.keys())}"
    )
    return None
