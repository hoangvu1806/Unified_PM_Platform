"""Run VA without the Google ADK graph — plain Python + HTTP.

ADK session storage may still hold the control key (same session_id).
The agent *graph* is optional: JS can POST /api/va/... directly.
"""

from __future__ import annotations

from typing import Any

from factory_wiki.store import get_wiki_store
from agents.ba_agent.section_gate import SECTION_FLAG_KEYS
from agents.sub_graph.validation_agent.logic import run_va_turn
from managers.control.session import load_control_state, persist_control_delta
from managers.database import connection as db_connection
from managers.database.models import BaPackageModel
from managers.service.state_helpers import (
    build_state_update_payload,
    persist_session_artifacts,
)


def hydrate_package_into_state(state: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Fill artifacts/flags from BA package rows if ADK state is thin."""
    db = db_connection.SessionLocal()
    try:
        pkg = db.get(BaPackageModel, session_id)
        if pkg is None:
            return state
        artifacts = dict(state.get("artifacts") or {})
        flags = dict(state.get("flags") or {})
        for sec in pkg.sections:
            data = dict(sec.data or {})
            sid = sec.section_id
            if sid == "feature_definition" and not artifacts.get("feature_definition"):
                artifacts["feature_definition"] = data
            elif sid == "business_rules" and not artifacts.get("business_rules"):
                artifacts["business_rules"] = data.get("business_rules") or data.get("items") or []
            elif sid == "workflow" and not artifacts.get("workflow"):
                artifacts["workflow"] = data
            elif sid == "use_cases" and not artifacts.get("use_cases"):
                artifacts["use_cases"] = data.get("use_cases") or data.get("items") or []
            elif sid == "bpmn_reference" and not artifacts.get("bpmn_reference"):
                artifacts["bpmn_reference"] = data
            elif sid == "ui_touchpoints" and not artifacts.get("ui_touchpoints"):
                artifacts["ui_touchpoints"] = data.get("ui_touchpoints") or data.get("items") or []
            flag_key = SECTION_FLAG_KEYS.get(sid)
            if flag_key and sec.flags and not flags.get(flag_key):
                flags[flag_key] = dict(sec.flags)
        if pkg.feature_title:
            state.setdefault("feature_title", pkg.feature_title)
        state["artifacts"] = artifacts
        state["flags"] = flags
        return state
    finally:
        db.close()


def _va_persist_fields(state: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    for key in (
        "feature_status",
        "last_validation",
        "_va_result",
        "_va_evidence",
        "_va_last_snapshot_hash",
        "_va_envelope",
        "package_exported",
    ):
        if key in state:
            updates[key] = state.get(key)
    return updates


async def execute_va_turn(
    session_id: str,
    *,
    user_id: str | None = None,
    user_message: str = "",
    run_validate: bool = False,
) -> dict[str, Any]:
    """Execute one VA turn in-process. No ADK Workflow / Runner."""
    state = await load_control_state(session_id, user_id)
    hydrate_package_into_state(state, session_id)
    state.setdefault("session_id", session_id)
    if run_validate:
        state["_va_run_validate"] = True

    store = get_wiki_store()
    try:
        text = run_va_turn(state, store, user_message or "")
    finally:
        store.close()

    updates = _va_persist_fields(state)
    if updates:
        state = await persist_control_delta(session_id, updates, user_id=user_id)
        hydrate_package_into_state(state, session_id)
    persist_session_artifacts(state, session_id)

    payload = build_state_update_payload(state)
    last = state.get("last_validation") or state.get("_va_result") or {}
    return {
        "runtime": "plain",
        "session_id": session_id,
        "agent_response": text or str(last.get("agent_response") or ""),
        "feature_status": payload.get("feature_status"),
        "last_validation": last if isinstance(last, dict) else {},
        "state": payload,
    }
