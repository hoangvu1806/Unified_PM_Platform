"""Callbacks for Feature Definition Extractor Node."""

from __future__ import annotations

import json

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from agents.sub_graph.feature_definition.schemas import FeatureDefinitionData
from callbacks.inject_context import insert_context
from managers.artifact.artifact_manager import merge_feature_definition_data
from utils import logging
from utils.utils import parse_str_to_dict

logger = logging()


async def fd_merge_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> None:
    """
    Merge delta Feature Definition data output from LLM to `ctx.state['artifacts']['feature_definition']`.
    """

    parsed: FeatureDefinitionData | None = None

    raw_text = llm_response.content.parts[0].text
    parsed_dict = parse_str_to_dict(raw_text)
    if parsed_dict:
        try:
            parsed = FeatureDefinitionData.model_validate(parsed_dict)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"fd_merge_callback: Failed to validate dict from text: {e}")

    if not parsed:
        logger.warning("fd_merge_callback: llm_response.parsed is null or invalid")
        return

    ctx_state = callback_context.state
    artifacts = ctx_state.get("artifacts", {})
    current_fd = artifacts.get("feature_definition", {})

    current_data = FeatureDefinitionData(
        goal=current_fd.get("goal") or "",
        actors=current_fd.get("actors") or [],
        scope_in=current_fd.get("scope_in") or [],
        scope_out=current_fd.get("scope_out") or [],
    )

    merged = merge_feature_definition_data(current_data, parsed)

    artifacts["feature_definition"] = {
        "goal": merged.goal,
        "actors": merged.actors,
        "scope_in": merged.scope_in,
        "scope_out": merged.scope_out,
    }
    # Reassign top-level state key to trigger ADK State.__setitem__ and commit delta to session storage
    ctx_state["artifacts"] = artifacts

    logger.info(
        f"fd_merge_callback: [ARTIFACT STATE] Merged FD delta into state: {ctx_state['artifacts']['feature_definition']}"
    )


async def fd_extractor_inject_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> None:
    """
    Inject current Feature Definition current artifact into context.
    """
    state = callback_context.state
    artifacts = state.get("artifacts", {}).get("feature_definition", {})

    current_data_str = json.dumps(
        {
            "goal": artifacts.get("goal") or "",
            "actors": artifacts.get("actors") or [],
            "scope_in": artifacts.get("scope_in") or [],
            "scope_out": artifacts.get("scope_out") or [],
        },
        ensure_ascii=False,
    )

    context_text = f"=== CURRENT DATA OF feature_definition ===\n{current_data_str}"
    insert_context(llm_request, context_text)
    logger.info(
        f"fd_extractor_inject_callback: [ARTIFACT STATE] Current FD Artifact = {artifacts}"
    )
