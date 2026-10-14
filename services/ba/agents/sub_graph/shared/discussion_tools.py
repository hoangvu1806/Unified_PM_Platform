"""ADK FunctionTools for BA discussion agents (FD / UC / WF).

Search/fetch approved wiki only. Never register approve / ingest / propose.
Optional web_search when Brave or Tavily env key is present.
preview_bpmn sketches from current workflow markdown (does not bypass flags).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from google.adk.tools import FunctionTool, ToolContext

from factory_wiki.store import AGENT_BA, WikiStore, get_wiki_store
from managers.control.bpmn import build_bpmn_xml, resolve_active_story_id


def _state_mapping(tool_context: ToolContext) -> dict[str, Any]:
    """ADK ``State`` has no ``keys()`` — ``dict(state)`` raises ``KeyError: 0``."""
    state = tool_context.state
    if state is None:
        return {}
    if isinstance(state, dict):
        return state
    to_dict = getattr(state, "to_dict", None)
    if callable(to_dict):
        try:
            out = to_dict()
            if isinstance(out, dict):
                return out
        except Exception:
            pass
    out: dict[str, Any] = {}
    for key in ("project_id", "session_id", "feature_id"):
        try:
            val = state.get(key) if hasattr(state, "get") else None
        except Exception:
            val = None
        if val is not None:
            out[key] = val
    return out


def _project_id(tool_context: ToolContext) -> str:
    from managers.control.session import resolve_project_id

    return resolve_project_id(_state_mapping(tool_context))


def _store() -> WikiStore:
    return get_wiki_store()


def _wiki_search_pages(tool_context: ToolContext, query: str, limit: int = 5) -> str:
    """Search approved wiki pages by keyword. Always try wiki before inventing facts.

    Returns approved hits only (title, page_id, snippet). Drafts never appear.
    """
    project_id = _project_id(tool_context)
    try:
        hits = _store().search(
            str(query or "").strip(),
            project_id=project_id,
            status="approved",
            limit=max(1, min(int(limit or 5), 20)),
            agent_name=AGENT_BA,
        )
    except PermissionError as exc:
        return json.dumps({"ok": False, "error": str(exc), "hits": []}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": f"wiki search failed: {exc}", "hits": []},
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "ok": True,
            "project_id": project_id,
            "query": query,
            "hits": hits,
            "note": (
                "Approved wiki only (this project_id + company namespace). "
                "Do not treat as editable; agents cannot approve."
            ),
        },
        ensure_ascii=False,
    )


def _wiki_fetch_page(tool_context: ToolContext, page_id: str) -> str:
    """Fetch one approved wiki page body by page_id after search."""
    project_id = _project_id(tool_context)
    pid = str(page_id or "").strip()
    if not pid:
        return json.dumps({"ok": False, "error": "page_id required"}, ensure_ascii=False)
    try:
        page = _store().fetch(pid, project_id=project_id, agent_name=AGENT_BA)
    except PermissionError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"wiki fetch failed: {exc}"}, ensure_ascii=False)
    if not page:
        return json.dumps(
            {"ok": False, "error": "page not found or not approved", "page_id": pid},
            ensure_ascii=False,
        )
    return json.dumps({"ok": True, "page": page}, ensure_ascii=False)


def _scope_out_items(tool_context: ToolContext) -> list[str]:
    state = tool_context.state or {}
    artifacts = state.get("artifacts") or {}
    fd = artifacts.get("feature_definition") if isinstance(artifacts, dict) else None
    if not isinstance(fd, dict):
        fd = artifacts if isinstance(artifacts, dict) else {}
    raw = fd.get("scope_out") if isinstance(fd, dict) else None
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _query_targets_scope_out(query: str, scope_out: list[str]) -> str | None:
    """Return the matching scope_out item if query casually targets a non-goal."""
    q = " ".join(str(query or "").lower().split())
    if not q:
        return None
    for item in scope_out:
        needle = " ".join(item.lower().split())
        if len(needle) < 3:
            continue
        if needle in q or q in needle:
            return item
    return None


def _web_search(tool_context: ToolContext, query: str, limit: int = 5) -> str:
    """Optional web search after wiki miss for in-package BA clarification.

    Do NOT use for FD scope_out / non-goals / unrelated browsing — refuse and stay
    in the package (wiki / OQ). Prefer wiki.search_pages first.

    Uses Brave or Tavily if an API key is configured. If not configured, returns
    a clear message — do not hallucinate results. Never treat web hits as approved wiki.
    """
    q = str(query or "").strip()
    if not q:
        return json.dumps({"ok": False, "error": "query required"}, ensure_ascii=False)

    blocked = _query_targets_scope_out(q, _scope_out_items(tool_context))
    if blocked:
        return json.dumps(
            {
                "ok": False,
                "error": "web_search refused for scope_out / non-goal topic",
                "scope_out_item": blocked,
                "detail": (
                    "Topic is listed in FD scope_out. Do not browse the web for it — "
                    "keep it out of scope, prefer wiki, or raise OQ if the user insists."
                ),
                "results": [],
            },
            ensure_ascii=False,
        )

    brave = (os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
    tavily = (os.environ.get("TAVILY_API_KEY") or "").strip()
    n = max(1, min(int(limit or 5), 10))

    if brave:
        try:
            results = _brave_search(q, brave, n)
            return json.dumps(
                {
                    "ok": True,
                    "provider": "brave",
                    "query": q,
                    "results": results,
                    "note": "Web hits are not approved wiki. Cite URLs; prefer wiki when available.",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": f"brave search failed: {exc}", "provider": "brave"},
                ensure_ascii=False,
            )

    if tavily:
        try:
            results = _tavily_search(q, tavily, n)
            return json.dumps(
                {
                    "ok": True,
                    "provider": "tavily",
                    "query": q,
                    "results": results,
                    "note": "Web hits are not approved wiki. Cite URLs; prefer wiki when available.",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": f"tavily search failed: {exc}", "provider": "tavily"},
                ensure_ascii=False,
            )

    return json.dumps(
        {
            "ok": False,
            "error": "web search not configured",
            "detail": (
                "Set BRAVE_API_KEY (or BRAVE_SEARCH_API_KEY) or TAVILY_API_KEY to enable. "
                "Do not invent search results."
            ),
            "results": [],
        },
        ensure_ascii=False,
    )


def _brave_search(query: str, api_key: str, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "count": str(limit)})
    req = urllib.request.Request(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    out: list[dict[str, Any]] = []
    for item in (payload.get("web") or {}).get("results") or []:
        out.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("description") or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def _tavily_search(query: str, api_key: str, limit: int) -> list[dict[str, Any]]:
    body = json.dumps(
        {"api_key": api_key, "query": query, "max_results": limit, "include_answer": False}
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    out: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        out.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("content") or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def _preview_bpmn(tool_context: ToolContext) -> str:
    """Preview BPMN XML from current workflow (lanes/gateways/DI). Sketch until flags pass.

    Calls deterministic build_bpmn_xml; does not bypass section flags or write approve.
    """
    state = tool_context.state
    artifacts = state.get("artifacts") or {}
    workflow = artifacts.get("workflow") or {}
    md = str(workflow.get("workflow_md_content") or "").strip()
    if not md:
        return json.dumps(
            {
                "ok": False,
                "error": "workflow markdown empty — write Main Flow actor steps first",
            },
            ensure_ascii=False,
        )
    fd = artifacts.get("feature_definition") or {}
    actors = fd.get("actors") if isinstance(fd, dict) else None
    allowed = [str(a) for a in actors] if isinstance(actors, list) else None
    title = str(state.get("feature_title") or "BA Feature")
    story_id = resolve_active_story_id(state)
    xml = build_bpmn_xml(
        feature_title=title,
        workflow_md=md,
        artifact_id=f"PREVIEW-{story_id}",
        allowed_actors=allowed,
        story_id=story_id,
    )
    # Keep response bounded for the model
    preview = xml if len(xml) <= 12000 else xml[:12000] + "\n<!-- truncated -->\n"
    return json.dumps(
        {
            "ok": True,
            "story_id": story_id,
            "note": (
                "BPMN preview is a sketch from WF actor steps (collaboration + lanes + DI). "
                "Does not bypass flags. Not approved wiki."
            ),
            "bpmn_xml": preview,
            "chars": len(xml),
        },
        ensure_ascii=False,
    )


def _as_tool(fn: Any, name: str) -> FunctionTool:
    fn.__name__ = name
    fn.__qualname__ = name
    return FunctionTool(fn)


def discussion_tools(*, include_preview_bpmn: bool = True) -> list[FunctionTool]:
    """Tools for FD + User Story discussion (and WF when BPMN questions arise)."""
    tools = [
        _as_tool(_wiki_search_pages, "wiki.search_pages"),
        _as_tool(_wiki_fetch_page, "wiki.fetch_page"),
        _as_tool(_web_search, "web_search"),
    ]
    if include_preview_bpmn:
        tools.append(_as_tool(_preview_bpmn, "preview_bpmn"))
    return tools


DISCUSSION_TOOL_NAMES = frozenset(
    {"wiki.search_pages", "wiki.fetch_page", "web_search", "preview_bpmn"}
)

# Deny list — never register these on discussion agents
FORBIDDEN_DISCUSSION_TOOLS = frozenset(
    {
        "wiki.approve_page",
        "wiki.demote_page",
        "wiki.delete_page",
        "wiki.ingest_source",
        "wiki.propose_page",
        "approve",
        "ingest",
        "propose",
    }
)
