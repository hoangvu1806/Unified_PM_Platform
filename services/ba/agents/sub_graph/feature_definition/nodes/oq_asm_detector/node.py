"""Node definition for OQ & ASM Detector Node."""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from agents.sub_graph.feature_definition.schemas import OQASMDetectionData
from agents.sub_graph.feature_definition.schemas import OQFollowThroughData
from callbacks.filter_history import create_history_filter
from config.model_config import base_model

from .callback import (
    oq_asm_inject_context_callback,
    oq_asm_merge_callback,
    oq_followthrough_before,
    oq_followthrough_merge,
)

def create_oq_asm_detector_node():
    """Create OQ & ASM Detector LLM Agent node."""
    prompt_path = Path(__file__).parent / "prompt.md"
    instruction = (
        prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    ) + (
        "\n\nWhen resolving an OQ, inspect ALL CURRENT BA ARTIFACTS and populate "
        "open_questions[].affected_artifacts and resolved_questions[].affected_artifacts with every affected existing FD/BR/WF/US/UI-touchpoint ID "
        "that must change to reflect the answer. Do not mark the OQ resolved if the "
        "answer is insufficient. These references drive a sequential follow-through "
        "agent before the user-facing reply."
    )

    return LlmAgent(
        name="oq_asm_detector",
        model=base_model,
        instruction=instruction,
        output_schema=OQASMDetectionData,
        before_model_callback=[
            create_history_filter(process_latest_message_only=True),
            oq_asm_inject_context_callback,
        ],
        after_model_callback=oq_asm_merge_callback,
    )


oq_asm_detector_node = create_oq_asm_detector_node()


def create_oq_followthrough_node():
    """Apply OQ-driven changes to referenced BA artifacts after fan-in."""
    return LlmAgent(
        name="oq_artifact_followthrough",
        model=base_model,
        instruction=(
            "You synchronize resolved BA Open Questions into existing artifacts. "
            "Use only the supplied answers and referenced artifacts. The supplied target list has already been expanded to include matching BR, WF, US, and UI touchpoints; "
            "review every listed artifact and update every part that must reflect the decision. "
            "When one artifact changes, ensure its listed downstream artifacts remain consistent too. "
            "Do not ask the user to identify the artifacts or to request synchronization. "
            "Return an update for every listed artifact that must change, or include the reviewed OQ ID and a concrete no_change_reason when no listed artifact needs a change. "
            "Return updated_value as valid JSON text without Markdown fences for each FD/BR/US/UI touchpoint, and a complete markdown block with its WF-ID heading for each WF. "
            "Never alter unrelated artifacts, invent new scope, or omit existing facts/BR references. "
            "Each update must include the OQ ID, artifact type, exact artifact ID, and updated_value. "
            "If no artifact needs a change, list the reviewed OQ ID and give a concrete no_change_reason. "
            "If a referenced artifact is absent from the supplied context, do not claim it was reviewed or synchronized. "
            "If an answer is ambiguous or a required update cannot be made safely, do not claim it is synchronized; "
            "return only the updates that are certain and leave the OQ pending for clarification."
        ),
        output_schema=OQFollowThroughData,
        before_model_callback=[
            create_history_filter(process_latest_message_only=True),
            oq_followthrough_before,
        ],
        after_model_callback=oq_followthrough_merge,
    )


oq_followthrough_node = create_oq_followthrough_node()

