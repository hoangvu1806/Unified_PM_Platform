"""Discussion Node — wiki search/fetch, optional web_search, BPMN preview."""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from agents.sub_graph.shared.discussion_tools import discussion_tools
from callbacks.filter_history import create_history_filter
from config.model_config import base_model

from .callback import fd_discussion_inject_callback

_TOOLS_HINT = (
    "\n\n# TOOLS\n"
    "You have tools. Search wiki (`wiki.search_pages` / `wiki.fetch_page`) before inventing. "
    "Do NOT `web_search` for FD `scope_out` / non-goals / unrelated browsing — refuse or OQ. "
    "Use `web_search` only after wiki miss for in-package BA clarification; "
    "if web search is not configured, say so — do not hallucinate. "
    "`preview_bpmn` is a sketch from WF steps (not needed for FD). "
    "Never approve, ingest, or propose wiki pages.\n"
)


def create_fd_discussion_node():
    """Create Feature Definition discussion LLM Agent with read-only wiki/web tools."""
    prompt_path = Path(__file__).parent / "prompt.md"
    instruction = (
        prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    )
    # Replace outdated "no tools" note if present
    instruction = instruction.replace(
        "> **Lưu ý**: Bạn KHÔNG có tool nào. Việc đánh giá ngữ nghĩa (semantic) được thực hiện tự động bởi hệ thống trước khi đến lượt bạn. Bạn chỉ cần đọc CHECKLIST và tương tác với user.",
        "> **Lưu ý**: Semantic flags được hệ thống đánh giá trước lượt bạn. Bạn có tool wiki/web — dùng wiki trước khi bịa. Không approve/ingest wiki.",
    )
    if "# TOOLS" not in instruction:
        instruction = instruction.rstrip() + _TOOLS_HINT

    return LlmAgent(
        name="fd_discussion",
        model=base_model,
        instruction=instruction,
        tools=discussion_tools(include_preview_bpmn=True),
        before_model_callback=[
            create_history_filter(visible_authors=["fd_discussion"], max_turns=5),
            fd_discussion_inject_callback,
        ],
    )
