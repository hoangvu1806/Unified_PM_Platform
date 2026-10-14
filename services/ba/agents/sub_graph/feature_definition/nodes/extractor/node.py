"""Node definition for Feature Definition Extractor Node."""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from agents.sub_graph.feature_definition.schemas import FeatureDefinitionData
from callbacks.filter_history import create_history_filter
from config.model_config import base_model

from .callback import fd_extractor_inject_callback, fd_merge_callback


def create_fd_extractor_node():
    """
    Create Feature Definition extractor LLM Agent node.
    """
    prompt_path = Path(__file__).parent / "prompt.md"
    instruction = (
        prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    )

    return LlmAgent(
        name="fd_extractor",
        model=base_model,
        instruction=instruction,
        output_schema=FeatureDefinitionData,
        before_model_callback=[
            create_history_filter(visible_authors=["fd_discussion"], max_turns=5),
            fd_extractor_inject_callback,
        ],
        after_model_callback=fd_merge_callback,
    )
