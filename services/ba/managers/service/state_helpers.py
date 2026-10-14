"""Build API responses from ADK session state."""

from __future__ import annotations

from typing import Any

from agents.ba_agent.constants import (
    DEFAULT_SECTION,
    STATE_ACTIVE_SECTION,
    STATE_ACTIVE_USER_STORY_ID,
    STATE_FEATURE_STATUS,
    STATE_SECTIONS_STATUS,
    STATE_TICKET_TYPE,
    TIER1_SECTIONS,
    USER_FACING_AUTHORS,
)
from agents.ba_agent.section_gate import (
    SECTION_FLAG_KEYS,
    can_proceed_to_validation,
    section_is_complete,
    sync_sections_status_from_flags,
)
from managers.artifact.artifact_manager import canonicalize_actor
from managers.control.session import write_package_status
from managers.control.status import (
    can_export,
    is_chat_frozen,
    normalize_feature_status,
    package_was_exported,
)
from managers.database.package_repository import BaPackageRepository
from managers.service.schema import ExtraDataInfo, SectionStatusInfo


def is_user_facing_author(author: str | None) -> bool:
    """True when event text should be shown to the end user."""
    return bool(author) and author in USER_FACING_AUTHORS


def apply_request_to_session_state(state: dict[str, Any], req) -> None:
    if req.active_section:
        state[STATE_ACTIVE_SECTION] = req.active_section
    if req.action and req.action.value == "validate":
        state["_validate_action"] = True
    assets = getattr(req, "assets", None) or []
    if assets:
        current = list(state.get("reference_assets") or [])
        by_id = {str(item.get("id")): item for item in current if isinstance(item, dict)}
        for asset in assets:
            item = asset.model_dump() if hasattr(asset, "model_dump") else dict(asset)
            by_id[str(item["id"])] = item
        state["reference_assets"] = list(by_id.values())


def request_state_delta(req) -> dict[str, Any]:
    """Build state_delta for ``Runner.run_async`` (safe; no extra append_event).

    Do not call ``session_service.append_event`` before run_async — that races
    with the runner and raises: session has been modified in storage.
    """
    delta: dict[str, Any] = {}
    if req.active_section:
        delta[STATE_ACTIVE_SECTION] = req.active_section
    if getattr(req, "ticket_type", None) is not None:
        delta[STATE_TICKET_TYPE] = req.ticket_type.value
    if req.action and req.action.value == "validate":
        delta["_validate_action"] = True
    assets = getattr(req, "assets", None) or []
    if assets:
        delta["reference_assets"] = [
            asset.model_dump() if hasattr(asset, "model_dump") else dict(asset)
            for asset in assets
        ]
    return delta


def build_section_status(state: dict[str, Any]) -> tuple[SectionStatusInfo, ExtraDataInfo]:
    sync_sections_status_from_flags(state)
    current_sec = state.get(STATE_ACTIVE_SECTION, DEFAULT_SECTION)
    sections_map = dict(state.get(STATE_SECTIONS_STATUS, {}))
    for sec in TIER1_SECTIONS:
        sections_map.setdefault(sec, "not_started")

    feature_status = normalize_feature_status(state.get(STATE_FEATURE_STATUS, "DRAFT"))
    last_va = state.get("last_validation") or state.get("_va_result") or {}
    last_va = last_va if isinstance(last_va, dict) else {}
    can_validate = can_proceed_to_validation(state)
    export_ok = can_export(feature_status, last_va)

    buttons: list[str] = []
    if can_validate:
        buttons.append("Validate ngay")
    if export_ok:
        buttons.append("Export BA Package")

    return SectionStatusInfo(
        current_section=current_sec,
        can_proceed_to_validation=can_validate,
        feature_status=feature_status,
        can_export=export_ok,
        sections=sections_map,
    ), ExtraDataInfo(buttons=buttons)


def build_state_update_payload(state: dict[str, Any]) -> dict[str, Any]:
    """Payload for SSE state.update / sync extra fields."""
    section_status, _extra = build_section_status(state)
    current = state.get(STATE_ACTIVE_SECTION, DEFAULT_SECTION)
    return {
        "select_section": current,
        "section_completable": bool(state.get("section_completable")),
        "can_proceed_to_validation": section_status.can_proceed_to_validation,
        "feature_status": section_status.feature_status,
        "can_export": section_status.can_export,
        "package_exported": package_was_exported(state),
        "chat_frozen": is_chat_frozen(
            section_status.feature_status,
            package_was_exported(state),
        ),
        "wiki_evidence": list(state.get("_va_evidence") or []),
        "sections_status": dict(section_status.sections),
        "active_user_story_id": state.get(STATE_ACTIVE_USER_STORY_ID),
        "artifacts": dict(state.get("artifacts", {})),
        "flags": dict(state.get("flags", {})),
        "open_questions": list(state.get("open_questions", [])),
        "assumptions": list(state.get("assumptions", [])),
        "reference_assets": list(state.get("reference_assets") or []),
        "last_validation": dict(state.get("last_validation") or state.get("_va_result") or {}),
        "data": _artifact_for_section(state, current),
        "flags_for_section": _flags_for_section(state, current),
    }


def _artifact_for_section(state: dict[str, Any], section_id: str) -> Any:
    artifacts = state.get("artifacts", {})
    if section_id == "feature_definition":
        return _normalized_feature_definition(artifacts)
    if section_id == "business_rules":
        return {"business_rules": artifacts.get("business_rules", [])}
    if section_id == "workflow":
        return artifacts.get("workflow", {})
    if section_id == "use_cases":
        return {"use_cases": artifacts.get("use_cases", [])}
    if section_id == "bpmn_reference":
        return artifacts.get("bpmn_reference") or {}
    if section_id == "ui_touchpoints":
        items = artifacts.get("ui_touchpoints") or []
        if isinstance(items, dict):
            items = items.get("ui_touchpoints") or items.get("items") or []
        return {"ui_touchpoints": items}
    return artifacts.get(section_id, {})


def _normalized_feature_definition(artifacts: dict[str, Any]) -> dict[str, Any]:
    """Repair legacy actor labels when projecting state to the UI/database."""
    data = dict(artifacts.get("feature_definition", {}) or {})
    data["actors"] = [
        canonical
        for actor in data.get("actors", [])
        if (canonical := canonicalize_actor(str(actor)))
    ]
    return data


def _flags_for_section(state: dict[str, Any], section_id: str) -> dict[str, Any]:
    key = SECTION_FLAG_KEYS.get(section_id, "")
    return dict(state.get("flags", {}).get(key, {}))


def persist_session_artifacts(
    state: dict[str, Any],
    session_id: str,
    repo: BaPackageRepository | None = None,
) -> None:
    """Project ADK session artifacts/flags into Postgres BaPackageSection rows."""
    if not session_id:
        return
    sync_sections_status_from_flags(state)
    repository = repo or BaPackageRepository()
    artifacts = state.get("artifacts", {})
    flags_root = state.get("flags", {})

    for section_id in TIER1_SECTIONS:
        flag_key = SECTION_FLAG_KEYS[section_id]
        if section_id == "feature_definition":
            data = _normalized_feature_definition(artifacts)
        elif section_id == "business_rules":
            data = {"business_rules": artifacts.get("business_rules", []) or []}
        elif section_id == "workflow":
            data = artifacts.get("workflow", {}) or {}
        elif section_id == "use_cases":
            data = {"use_cases": artifacts.get("use_cases", []) or []}
        else:
            data = {}

        section_flags = flags_root.get(flag_key, {}) or {}
        repository.save_section(
            session_id=session_id,
            section_id=section_id,
            data=data if isinstance(data, dict) else {},
            flags=section_flags,
            is_completable=section_is_complete(state, section_id),
        )

    _persist_group2_sections(state, session_id, repository)
    write_package_status(
        session_id,
        normalize_feature_status(state.get(STATE_FEATURE_STATUS, "DRAFT")),
    )


def _persist_group2_sections(
    state: dict[str, Any],
    session_id: str,
    repository: BaPackageRepository,
) -> None:
    artifacts = state.get("artifacts") or {}
    bpmn = artifacts.get("bpmn_reference")
    if isinstance(bpmn, dict) and bpmn:
        repository.save_section(
            session_id=session_id,
            section_id="bpmn_reference",
            data=bpmn,
            flags={},
            is_completable=bool(bpmn.get("bpmn_xml_content")),
        )
    touchpoints = artifacts.get("ui_touchpoints")
    if isinstance(touchpoints, dict):
        touchpoints = touchpoints.get("ui_touchpoints") or touchpoints.get("items") or []
    if isinstance(touchpoints, list) and touchpoints:
        repository.save_section(
            session_id=session_id,
            section_id="ui_touchpoints",
            data={"ui_touchpoints": touchpoints},
            flags={},
            is_completable=True,
        )


def feature_status_label(state: dict[str, Any]) -> str:
    return state.get(STATE_FEATURE_STATUS, "DRAFT")
