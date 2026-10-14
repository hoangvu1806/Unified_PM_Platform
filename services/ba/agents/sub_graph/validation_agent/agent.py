"""Validation Agent — nested ADK Workflow (rules first, LLM never decides PASS/FAIL)."""

from __future__ import annotations

from google.adk import Context
from google.adk.workflow import Workflow, node

from agents.sub_graph.validation_agent.logic import run_va_turn
from agents.sub_graph.validation_agent.nodes.discussion.node import create_va_discuss_node
from agents.sub_graph.validation_agent.nodes.explain import va_explain_node
from factory_wiki.store import get_wiki_store

ROUTE_VA_RUN = "va_run"
ROUTE_VA_DISCUSS = "va_discuss"


def _user_text(ctx: Context) -> str:
    content = getattr(ctx, "user_content", None)
    parts = getattr(content, "parts", None) or []
    if parts:
        return getattr(parts[0], "text", "") or ""
    return ""


def route_va_turn(ctx: Context) -> str:
    """Validate (rules) vs discuss (LLM). Used by the graph node and unit tests."""
    user_text = _user_text(ctx)
    state = ctx.state
    if state.get("_validate_action"):
        state["_va_run_validate"] = True
        state["_validate_action"] = False
    wants_validate = bool(state.get("_va_run_validate")) or str(user_text).strip().startswith(
        "[VALIDATE]"
    )
    ctx.route = ROUTE_VA_RUN if wants_validate else ROUTE_VA_DISCUSS
    return user_text


@node(name="va_router")
def va_router_node(ctx: Context) -> str:
    return route_va_turn(ctx)


@node(name="va_report")
def va_report_node(ctx: Context) -> str:
    """Python rules only. LLM commentary is the next node (optional)."""
    user_text = _user_text(ctx)
    if ctx.state.get("_validate_action"):
        ctx.state["_va_run_validate"] = True
        ctx.state["_validate_action"] = False
    ctx.state["_va_run_validate"] = True
    store = get_wiki_store()
    try:
        return run_va_turn(ctx.state, store, user_text, with_llm=False)
    finally:
        store.close()


def create_validation_agent() -> Workflow:
    discuss = create_va_discuss_node()
    return Workflow(
        name="validation_agent",
        edges=[
            ("START", va_router_node),
            (
                va_router_node,
                {
                    ROUTE_VA_RUN: va_report_node,
                    ROUTE_VA_DISCUSS: discuss,
                },
            ),
            (va_report_node, va_explain_node),
        ],
    )


va_subgraph = create_validation_agent()
