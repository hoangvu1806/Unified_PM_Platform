"""BR discussion node."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from callbacks.filter_history import create_history_filter
from config.model_config import base_model

from .callback import br_discussion_inject_callback


def create_br_discussion_node():
    return LlmAgent(
        name="br_discussion",
        model=base_model,
        instruction=(
            "Bạn là BA Agent, section Business Rules. "
            "Xác nhận rules theo CHECKLIST (ưu tiên required=true). "
            "Không dùng mã flag (BR-F1…) với User. "
            "Nhắc OQ/Assumptions nếu có. "
            "Gợi ý rule còn thiếu từ Feature Definition khi phù hợp."
        ),
        tools=[],
        before_model_callback=[
            create_history_filter(visible_authors=["br_discussion"], max_turns=3),
            br_discussion_inject_callback,
        ],
    )
