"""Shared schema + apply helper for semantic flag evaluation (no tool calling).

llm-gate Qwen rejects OpenAI ``tool_choice=auto``. Flags checkers therefore
return structured JSON and we merge into ``ctx.state['flags']`` in after_model.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agents.sub_graph.shared.constants import NOT_YET_REASONABLE, PASS
from utils.utils import parse_str_to_dict

VALID_SEMANTIC = frozenset({PASS, NOT_YET_REASONABLE})

# Valid empty payload for LlmAgent output_schema early-stop (must be JSON, not prose).
EMPTY_EVALUATION_JSON = '{"evaluations":[]}'


class SemanticFlagResult(BaseModel):
    flag_id: str = Field(..., description="e.g. FD-F1, BR-F4, WF-F2")
    status: str = Field(
        ...,
        description="PASS or NOT_YET_REASONABLE",
    )
    detail: str | None = Field(
        None,
        description="Required when NOT_YET_REASONABLE — why data is insufficient",
    )


class SemanticFlagsEvaluation(BaseModel):
    """Delta evaluations for all PENDING_SEMANTIC flags this turn."""

    evaluations: list[SemanticFlagResult] = Field(
        default_factory=list,
        description="One entry per pending semantic flag",
    )


def empty_evaluation_response():
    """LlmResponse body that satisfies SemanticFlagsEvaluation when skipping LLM."""
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text=EMPTY_EVALUATION_JSON)],
        )
    )


def apply_semantic_flag_evaluations(
    state: dict[str, Any],
    flag_bucket: str,
    raw_text: str | None,
) -> int:
    """Parse LLM JSON and write PASS / NOT_YET_REASONABLE into state flags.

    Returns number of flags updated.
    """
    # Lazy import avoids circular: ba_agent.__init__ → subgraphs → semantic_flags
    from agents.ba_agent.section_gate import sync_sections_status_from_flags

    if not raw_text:
        return 0
    parsed = parse_str_to_dict(raw_text)
    if not parsed:
        return 0
    try:
        data = SemanticFlagsEvaluation.model_validate(parsed)
    except Exception:
        if isinstance(parsed, list):
            try:
                data = SemanticFlagsEvaluation.model_validate({"evaluations": parsed})
            except Exception:
                return 0
        else:
            return 0

    all_flags = dict(state.get("flags", {}))
    bucket = dict(all_flags.get(flag_bucket, {}))
    updated = 0
    for item in data.evaluations:
        fid = item.flag_id.strip().upper()
        status = item.status.strip().upper()
        if status not in VALID_SEMANTIC:
            continue
        existing = dict(bucket.get(fid, {}))
        existing["status"] = status
        existing["detail"] = item.detail if status == NOT_YET_REASONABLE else None
        bucket[fid] = existing
        updated += 1
    all_flags[flag_bucket] = bucket
    state["flags"] = all_flags
    sync_sections_status_from_flags(state)
    return updated
