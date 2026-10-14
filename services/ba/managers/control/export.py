"""Export a VALIDATED BA Package as the Designer handoff envelope."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from agents.ba_agent.constants import STATE_FEATURE_STATUS
from managers.control.bpmn import ensure_bpmn_artifact
from managers.control.envelope import (
    AGENT_BA,
    AGENT_DESIGNER,
    ARTIFACT_BA_PACKAGE,
    CONTRACT_BA_OUTPUT,
    common_envelope,
)
from managers.control.session import (
    load_control_state,
    persist_control_delta,
    resolve_project_id,
)
from managers.control.status import (
    STATUS_EXPORTED,
    can_export,
    normalize_feature_status,
)
from managers.control.touchpoints import ensure_touchpoints_artifact


def _input_references(state: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in state.get("_va_evidence") or []:
        if isinstance(item, dict) and item.get("page_id"):
            refs.append(
                {
                    "type": "wiki_page",
                    "page_id": item.get("page_id"),
                    "title": item.get("title"),
                    "version": item.get("version"),
                }
            )
    last = state.get("last_validation") or {}
    for item in last.get("evidence_references") or []:
        if isinstance(item, dict) and item.get("page_id"):
            already = {r.get("page_id") for r in refs}
            if item["page_id"] not in already:
                refs.append(
                    {
                        "type": "wiki_page",
                        "page_id": item.get("page_id"),
                        "title": item.get("title"),
                        "version": item.get("version"),
                    }
                )
    return refs


def build_export_envelope(state: dict[str, Any]) -> dict[str, Any]:
    session_id = str(state.get("session_id") or state.get("feature_id") or "")
    project_id = resolve_project_id(state, session_id=session_id or None)
    last_va = state.get("last_validation") or state.get("_va_result") or {}
    outcome = last_va.get("status")
    payload = {
        "feature_title": state.get("feature_title"),
        "feature_description": state.get("feature_description"),
        "ticket_type": state.get("ticket_type"),
        "artifacts": state.get("artifacts") or {},
        "flags": state.get("flags") or {},
        "sections_status": state.get("sections_status") or {},
        "open_questions": state.get("open_questions") or [],
        "assumptions": state.get("assumptions") or [],
        "validation": last_va,
        "reference_assets": list(state.get("reference_assets") or []),
    }
    return common_envelope(
        correlation_id=session_id,
        project_id=project_id,
        feature_id=session_id,
        agent_id=AGENT_BA,
        contract_name=CONTRACT_BA_OUTPUT,
        artifact_type=ARTIFACT_BA_PACKAGE,
        artifact_status="proposed",
        payload=payload,
        input_references=_input_references(state),
        validation={
            "schema_valid": True,
            "errors": [],
            "outcome": outcome,
        },
        extra={
            "handoff": {
                "to": AGENT_DESIGNER,
                "gate": "G1",
                "mode": "feature_design",
                "ready": True,
                "note": (
                    "Control-plane handoff after VALIDATED. "
                    "Proposal G1 still requires human APPROVED + BPMN "
                    "before a live Designer run."
                ),
            }
        },
    )


async def export_validated_package(
    session_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    state = await load_control_state(session_id, user_id)
    status = normalize_feature_status(state.get(STATE_FEATURE_STATUS))
    last_va = state.get("last_validation") or state.get("_va_result") or {}
    if not can_export(status, last_va if isinstance(last_va, dict) else None):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Export requires feature_status=VALIDATED "
                f"(or EXPORTED with a current passed validation; current: {status})"
            ),
        )
    ensure_bpmn_artifact(state)
    ensure_touchpoints_artifact(state)
    envelope = build_export_envelope(state)
    await persist_control_delta(
        session_id,
        {
            STATE_FEATURE_STATUS: STATUS_EXPORTED,
            "package_exported": True,
            "artifacts": state.get("artifacts") or {},
        },
        user_id=user_id,
    )
    envelope["artifact"]["status"] = "proposed"
    return envelope
