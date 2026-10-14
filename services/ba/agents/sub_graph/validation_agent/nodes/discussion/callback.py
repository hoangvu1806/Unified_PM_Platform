"""Callbacks for Validation Agent discussion — read-only inject + snapshot restore."""

from __future__ import annotations

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from agents.sub_graph.validation_agent.llm import (
    build_readonly_context,
    capture_readonly_snapshot,
    restore_readonly_snapshot,
)
from callbacks.inject_context import insert_context
from utils import logging

logger = logging()


async def va_discuss_inject_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> None:
    """Inject last report + artifacts as read-only context. Snapshot mutable keys."""
    state = callback_context.state
    state["_va_readonly_snapshot"] = capture_readonly_snapshot(state)
    insert_context(llm_request, build_readonly_context(state))
    last = state.get("last_validation")
    outcome = last.get("status") if isinstance(last, dict) else None
    logger.info(
        f"va_discuss_inject_callback: outcome={outcome} feature_status={state.get('feature_status')}"
    )


async def va_discuss_after_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> None:
    """Restore artifacts/status so the LLM cannot persist PASS/FAIL or package edits."""
    state = callback_context.state
    snap = state.get("_va_readonly_snapshot")
    if isinstance(snap, dict) and snap:
        restore_readonly_snapshot(state, snap)
    logger.info(
        f"va_discuss_after_callback: restored readonly snapshot; feature_status={state.get('feature_status')}"
    )
