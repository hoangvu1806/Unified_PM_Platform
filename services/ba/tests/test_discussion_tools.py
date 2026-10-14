"""Tests for BA discussion ADK FunctionTools registration."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.sub_graph.feature_definition.nodes.discussion.node import (
    create_fd_discussion_node,
)
from agents.sub_graph.shared.discussion_tools import (
    DISCUSSION_TOOL_NAMES,
    FORBIDDEN_DISCUSSION_TOOLS,
    discussion_tools,
    _web_search,
)
from agents.sub_graph.use_cases.agent import _uc_discussion
from agents.sub_graph.workflow.agent import _wf_discussion


def test_discussion_tools_registered_names():
    tools = discussion_tools(include_preview_bpmn=True)
    names = {t.name for t in tools}
    assert names == DISCUSSION_TOOL_NAMES
    assert names.isdisjoint(FORBIDDEN_DISCUSSION_TOOLS)
    assert "wiki.approve_page" not in names
    assert "wiki.ingest_source" not in names
    assert "wiki.propose_page" not in names


def test_fd_uc_wf_discussion_have_tools():
    fd = create_fd_discussion_node()
    for agent in (fd, _uc_discussion, _wf_discussion):
        names = {t.name for t in (agent.tools or [])}
        assert "wiki.search_pages" in names
        assert "wiki.fetch_page" in names
        assert "web_search" in names
        assert "preview_bpmn" in names
        assert names.isdisjoint(FORBIDDEN_DISCUSSION_TOOLS)


def test_extractors_remain_tool_less():
    from agents.sub_graph.use_cases.agent import _uc_extractor, _uc_flags
    from agents.sub_graph.workflow.agent import _wf_extractor, _wf_flags

    for agent in (_uc_extractor, _uc_flags, _wf_extractor, _wf_flags):
        assert not agent.tools


def test_web_search_not_configured():
    mock_ctx = MagicMock()
    mock_ctx.state = {"project_id": "PRJ-MES-01"}
    # Ensure no keys in this process for the assertion
    import os

    saved = {
        k: os.environ.pop(k, None)
        for k in ("BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY", "TAVILY_API_KEY")
    }
    try:
        raw = _web_search(mock_ctx, "mes inventory")
        assert "not configured" in raw.lower()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_web_search_refuses_scope_out_topic():
    import json

    mock_ctx = MagicMock()
    mock_ctx.state = {
        "project_id": "PRJ-MES-01",
        "artifacts": {
            "feature_definition": {
                "scope_out": ["Thanh toán quốc tế", "Weekly meal plans"],
            }
        },
    }
    raw = _web_search(mock_ctx, "best practices for Thanh toán quốc tế")
    payload = json.loads(raw)
    assert payload.get("ok") is False
    assert "scope_out" in (payload.get("error") or "").lower()
    assert payload.get("results") == []
