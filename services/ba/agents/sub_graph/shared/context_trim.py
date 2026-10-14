"""Compact upstream artifacts for LLM inject — avoid dumping full FD into BR/WF/UC."""

from __future__ import annotations

from typing import Any


def trim_feature_definition(fd: Any, *, max_items: int = 12) -> dict[str, Any]:
    """Keep only fields BR/WF/UC need from Feature Definition."""
    if not isinstance(fd, dict):
        return {}
    return {
        "goal": _clip(fd.get("goal"), 400),
        "actors": _take_list(fd.get("actors"), max_items),
        "scope_in": _take_list(fd.get("scope_in"), max_items),
        "scope_out": _take_list(fd.get("scope_out"), max_items),
    }


def trim_open_items(items: Any, *, max_items: int = 8) -> list[Any]:
    if not isinstance(items, list):
        return []
    return items[-max_items:]


def trim_business_rules(rules: Any, *, max_rules: int = 20) -> list[dict[str, Any]]:
    """Compact BR list for WF/UC inject — id + clipped statement only."""
    if not isinstance(rules, list):
        return []
    out: list[dict[str, Any]] = []
    for rule in rules[:max_rules]:
        if not isinstance(rule, dict):
            continue
        out.append(
            {
                "id": rule.get("id"),
                "statement": _clip(rule.get("statement"), 200),
                "source": rule.get("source"),
            }
        )
    return out


def trim_workflow(wf: Any, *, max_md_chars: int = 2500) -> dict[str, Any]:
    """Shrink workflow artifact for inject; keep full md only when short."""
    if not isinstance(wf, dict):
        return {}
    md = str(wf.get("workflow_md_content") or "")
    if len(md) > max_md_chars:
        md = md[: max_md_chars - 1] + "…"
    return {
        "artifact_id": wf.get("artifact_id"),
        "version": wf.get("version"),
        "workflow_md_content": md or None,
    }

def _take_list(value: Any, max_items: int) -> list[Any]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:max_items]:
        if isinstance(item, str):
            out.append(_clip(item, 120))
        else:
            out.append(item)
    return out


def _clip(value: Any, limit: int) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
