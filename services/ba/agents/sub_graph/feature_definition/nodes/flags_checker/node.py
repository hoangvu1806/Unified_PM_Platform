"""Node definition for Feature Definition Flags Checker Node.

Architecture: LlmAgent with before_model_callback for early stop.
- before_model_callback runs logic check (check_fd_flags_logic)
- If no PENDING_SEMANTIC flags → early stop (skip LLM)
- If PENDING_SEMANTIC exists → LLM returns structured evaluations (no tools;
  llm-gate Qwen rejects tool_choice=auto)
"""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse

from agents.sub_graph.shared.semantic_flags import (
    SemanticFlagsEvaluation,
    apply_semantic_flag_evaluations,
)
from config.model_config import base_model

from .callback import fd_flags_checker_before_model


async def fd_flags_after_model(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> None:
    text = ""
    if llm_response.content and llm_response.content.parts:
        text = llm_response.content.parts[0].text or ""
    apply_semantic_flag_evaluations(callback_context.state, "fd", text)


def create_fd_flags_checker_node():
    """Create Feature Definition flags checker LlmAgent node."""
    prompt_path = Path(__file__).parent / "prompt.md"
    instruction = (
        prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    )
    # Prefer structured JSON over tool calls (gate does not support tool_choice=auto).
    instruction = (
        instruction
        + "\n\n# OUTPUT\n"
        "Trả về JSON đúng schema SemanticFlagsEvaluation: "
        '{"evaluations":[{"flag_id":"FD-F1","status":"PASS|NOT_YET_REASONABLE","detail":null}]}. '
        "KHÔNG gọi tool. Đánh giá MỌI flag trong PENDING SEMANTIC FLAGS."
    )

    return LlmAgent(
        name="fd_flags_checker",
        model=base_model,
        instruction=instruction,
        output_schema=SemanticFlagsEvaluation,
        before_model_callback=fd_flags_checker_before_model,
        after_model_callback=fd_flags_after_model,
    )
