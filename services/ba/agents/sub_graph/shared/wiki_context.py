"""Approved-wiki context for BA discussion inject (ack-then-delta).

Uses WikiStore search/list (approved only). Does not approve or write wiki.
Never auto-overwrite BA artifacts from wiki hits.
"""

from __future__ import annotations

import json
from typing import Any

from factory_wiki.store import WikiStore, get_wiki_store
from managers.control.session import resolve_project_id


def _feature_keywords(state: dict[str, Any]) -> list[str]:
    artifacts = state.get("artifacts") or {}
    fd = artifacts.get("feature_definition") or {}
    texts: list[str] = []
    for key in ("goal",):
        if fd.get(key):
            texts.append(str(fd[key]))
    for item in (fd.get("scope_in") or [])[:6]:
        texts.append(str(item))
    title = state.get("feature_title")
    if title:
        texts.append(str(title))
    out: list[str] = []
    seen: set[str] = set()
    for text in texts:
        cleaned = " ".join(str(text).split())
        if len(cleaned) < 4:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned[:80])
    return out[:8]


def collect_approved_wiki_hits(
    state: dict[str, Any],
    *,
    store: WikiStore | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Return approved wiki hits for the feature project (drafts never appear)."""
    project_id = resolve_project_id(state)
    own_store = store is None
    wiki = store or get_wiki_store()
    try:
        seen: set[str] = set()
        hits: list[dict[str, Any]] = []
        for hit in wiki.list_approved(
            project_id=project_id, agent_name="ba-agent", limit=limit
        ):
            pid = str(hit.get("page_id") or "")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            hits.append(hit)
        for query in _feature_keywords(state):
            for hit in wiki.search(
                query,
                project_id=project_id,
                agent_name="ba-agent",
                limit=8,
            ):
                pid = str(hit.get("page_id") or "")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                hits.append(hit)
                if len(hits) >= limit:
                    break
            if len(hits) >= limit:
                break
        return hits[:limit]
    finally:
        if own_store:
            wiki.close()


def format_approved_wiki_context(
    state: dict[str, Any],
    *,
    store: WikiStore | None = None,
    limit: int = 12,
) -> str:
    """Markdown/text block for LLM inject: acknowledge first, delta only."""
    hits = collect_approved_wiki_hits(state, store=store, limit=limit)
    header = (
        "=== APPROVED WIKI (already agreed) ===\n"
        "Rules: (1) Acknowledge existing wiki titles/ids first. "
        "(2) Only brainstorm the NEW idea if it is the same topic as this feature. "
        "(3) Do NOT auto-overwrite artifacts from wiki. "
        "(4) Agents never approve or write wiki — humans approve. "
        "(5) If the idea is a different product, mark scope_out / OQ; do not rewrite agreed text.\n"
    )
    if not hits:
        return header + "(no approved wiki pages for this project + company corpus)\n"
    compact = [
        {
            "page_id": h.get("page_id"),
            "title": h.get("title"),
            "snippet": h.get("snippet"),
            "version": h.get("version"),
        }
        for h in hits
    ]
    return header + json.dumps(compact, ensure_ascii=False, indent=2) + "\n"
