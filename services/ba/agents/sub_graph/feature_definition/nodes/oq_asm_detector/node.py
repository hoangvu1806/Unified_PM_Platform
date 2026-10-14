"""Node definition for OQ & ASM Detector Node."""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from agents.sub_graph.feature_definition.schemas import OQASMDetectionData
from callbacks.filter_history import create_history_filter
from config.model_config import base_model

from .callback import (
    oq_asm_inject_context_callback,
    oq_asm_merge_callback,
)

def create_oq_asm_detector_node():
    """Create OQ & ASM Detector LLM Agent node."""
    prompt_path = Path(__file__).parent / "prompt.md"
    instruction = (
        prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
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

