"""Optional LLM commentary after the deterministic VA report."""

from __future__ import annotations

from google.adk import Context
from google.adk.workflow import node

from agents.sub_graph.validation_agent.llm import explain_validation_with_llm


@node(name="va_explain")
def va_explain_node(ctx: Context) -> str:
    """Appendix only. Empty string if LLM is down — report already streamed."""
    try:
        return explain_validation_with_llm(ctx.state) or ""
    except Exception:  # noqa: BLE001
        return ""
