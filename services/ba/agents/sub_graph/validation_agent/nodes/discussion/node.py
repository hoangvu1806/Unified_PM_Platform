"""VA discussion LlmAgent — conversational, read-only, same company gate as FD/BR."""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from callbacks.filter_history import create_history_filter
from config.model_config import base_model

from .callback import va_discuss_after_callback, va_discuss_inject_callback


def create_va_discuss_node():
    prompt_path = Path(__file__).parent / "prompt.md"
    instruction = (
        prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    )
    return LlmAgent(
        name="va_discuss",
        model=base_model,
        instruction=instruction,
        tools=[],
        before_model_callback=[
            create_history_filter(visible_authors=["va_discuss", "va_explain", "va_report"], max_turns=8),
            va_discuss_inject_callback,
        ],
        after_model_callback=va_discuss_after_callback,
    )
