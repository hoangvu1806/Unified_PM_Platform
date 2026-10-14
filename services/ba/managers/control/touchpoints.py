"""UI Touchpoints — BA conclusion artifact for later Designer Agent handoff.

This is not a Designer UI. It is the screen/touchpoint list the PO/BA agreed
after Use Cases (and BPMN when present). Stored on the feature session and
included in the Common Envelope payload.
"""

from __future__ import annotations

import re
from typing import Any

from agents.ba_agent.section_gate import all_required_sections_complete
from managers.control.bpmn import parse_workflow_steps

INTERACTIONS = ("form", "display", "notification", "confirmation")


def can_generate_touchpoints(state: dict[str, Any]) -> bool:
    return all_required_sections_complete(state)


def _actor_id(raw: str) -> str:
    text = str(raw or "").strip()
    if ":" in text:
        text = text.split(":", 1)[0].strip()
    return text or "ACT-USER"


def normalize_touchpoint(item: dict[str, Any], index: int) -> dict[str, Any]:
    """Stable Designer-consumable fields + spec bpmn_node_id / interaction."""
    idx = index + 1
    tp_id = str(item.get("id") or f"UIT-{idx:02d}")
    name = str(item.get("name") or item.get("screen") or item.get("screen_name") or tp_id)
    actor = _actor_id(item.get("actor") or item.get("actor_id") or "")
    related = item.get("related_uc_ids") or item.get("use_case_ids") or []
    if isinstance(related, str):
        related = [related]
    related = [str(x) for x in related if str(x).strip()]
    interaction = str(item.get("interaction") or "form").lower()
    if interaction not in INTERACTIONS:
        interaction = "form"
    bpmn_node_id = str(item.get("bpmn_node_id") or f"Task_{idx}")
    return {
        "id": tp_id,
        "name": name,
        "actor": actor,
        "trigger": str(item.get("trigger") or ""),
        "screen": str(item.get("screen") or item.get("screen_name") or name),
        "goal": str(item.get("goal") or ""),
        "notes": str(item.get("notes") or ""),
        "related_uc_ids": related,
        "bpmn_node_id": bpmn_node_id,
        "interaction": interaction,
    }


def _guess_interaction(action: str, is_last: bool) -> str:
    text = (action or "").lower()
    if any(w in text for w in ("thông báo", "notify", "alert", "email")):
        return "notification"
    if any(w in text for w in ("xem", "hiển thị", "display", "list", "dashboard")):
        return "display"
    if is_last or any(w in text for w in ("xác nhận", "confirm", "approve", "phê duyệt")):
        return "confirmation"
    return "form"


def generate_touchpoints(state: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = state.get("artifacts") or {}
    workflow = artifacts.get("workflow") or {}
    md = str(workflow.get("workflow_md_content") or "")
    parsed = parse_workflow_steps(md)
    steps = parsed["steps"]
    use_cases = artifacts.get("use_cases") or []
    fd = artifacts.get("feature_definition") or {}
    actors = fd.get("actors") or []

    touchpoints: list[dict[str, Any]] = []
    if steps:
        for i, step in enumerate(steps):
            actor = _actor_id(step.get("actor") or "")
            action = step.get("action") or step.get("step") or f"Step {i + 1}"
            related = [
                str(uc.get("id"))
                for uc in use_cases
                if isinstance(uc, dict)
                and uc.get("id")
                and (
                    _actor_id(uc.get("actor_id") or "") == actor
                    or (actor and actor in str(uc.get("statement") or ""))
                )
            ]
            is_human = bool(actor) and not re.search(
                r"hệ thống|system|service", actor, re.IGNORECASE
            )
            if not is_human and i not in {0, len(steps) - 1}:
                continue
            touchpoints.append(
                normalize_touchpoint(
                    {
                        "id": f"UIT-{len(touchpoints) + 1:02d}",
                        "name": action,
                        "actor": actor or (actors[0] if actors else "ACT-USER"),
                        "trigger": action,
                        "screen": action,
                        "goal": str(fd.get("goal") or ""),
                        "notes": step.get("br_ref") or "",
                        "related_uc_ids": related[:4],
                        "bpmn_node_id": f"Task_{i + 1}",
                        "interaction": _guess_interaction(action, i == len(steps) - 1),
                    },
                    len(touchpoints),
                )
            )
    if not touchpoints:
        for i, uc in enumerate(use_cases):
            if not isinstance(uc, dict):
                continue
            touchpoints.append(
                normalize_touchpoint(
                    {
                        "id": f"UIT-{i + 1:02d}",
                        "name": uc.get("id") or f"Screen {i + 1}",
                        "actor": uc.get("actor_id") or "",
                        "trigger": uc.get("statement") or "",
                        "screen": uc.get("id") or f"Screen {i + 1}",
                        "goal": str(fd.get("goal") or ""),
                        "notes": "",
                        "related_uc_ids": [uc.get("id")] if uc.get("id") else [],
                        "bpmn_node_id": f"Task_{i + 1}",
                        "interaction": "form",
                    },
                    i,
                )
            )
    if not touchpoints:
        touchpoints.append(
            normalize_touchpoint(
                {
                    "id": "UIT-01",
                    "name": "Primary screen",
                    "actor": _actor_id(actors[0] if actors else "ACT-USER"),
                    "trigger": "User opens the feature",
                    "screen": str(state.get("feature_title") or "Feature screen"),
                    "goal": str(fd.get("goal") or ""),
                    "interaction": "form",
                    "bpmn_node_id": "Task_1",
                },
                0,
            )
        )
    return touchpoints


def ensure_touchpoints_artifact(
    state: dict[str, Any], *, force: bool = False
) -> list[dict[str, Any]] | None:
    if not can_generate_touchpoints(state):
        return None
    artifacts = dict(state.get("artifacts") or {})
    existing = artifacts.get("ui_touchpoints")
    if existing and not force:
        if isinstance(existing, dict):
            existing = existing.get("ui_touchpoints") or existing.get("items") or []
        if isinstance(existing, list) and existing:
            normalized = [normalize_touchpoint(item, i) for i, item in enumerate(existing)]
            artifacts["ui_touchpoints"] = normalized
            state["artifacts"] = artifacts
            return normalized
    items = generate_touchpoints(state)
    artifacts["ui_touchpoints"] = items
    state["artifacts"] = artifacts
    sections = dict(state.get("sections_status") or {})
    sections["ui_touchpoints"] = "completed"
    state["sections_status"] = sections
    return items


def replace_touchpoints(state: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_touchpoint(item, i) for i, item in enumerate(items)]
    artifacts = dict(state.get("artifacts") or {})
    artifacts["ui_touchpoints"] = normalized
    state["artifacts"] = artifacts
    return normalized
