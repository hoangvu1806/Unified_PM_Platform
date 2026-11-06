"""Sequential section gating for NEW_FEATURE ticket type."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agents.ba_agent.constants import (
    SECTION_BUSINESS_RULES,
    SECTION_FEATURE_DEFINITION,
    SECTION_USE_CASES,
    SECTION_WORKFLOW,
    STATE_ACTIVE_SECTION,
    TIER1_SECTIONS,
)
from agents.sub_graph.shared.constants import BLOCKER_STATUSES, PASS

SECTION_FLAG_KEYS: dict[str, str] = {
    SECTION_FEATURE_DEFINITION: "fd",
    SECTION_BUSINESS_RULES: "br",
    SECTION_WORKFLOW: "wf",
    SECTION_USE_CASES: "uc",
}

# Warning-only flags that never block section completion.
WARNING_FLAGS: dict[str, frozenset[str]] = {
    "fd": frozenset({"FD-F4"}),
    "br": frozenset({"BR-F2", "BR-F3", "BR-F5"}),
    "wf": frozenset({"WF-F3", "WF-F5", "WF-F6"}),
    "uc": frozenset({"UC-F4", "UC-F6"}),
}

# Every blocker must be present and non-blocking. Missing == incomplete.
REQUIRED_BLOCKERS: dict[str, frozenset[str]] = {
    "fd": frozenset({"FD-F1", "FD-F2", "FD-F3", "FD-F5"}),
    "br": frozenset({"BR-F1", "BR-F4"}),
    "wf": frozenset({"WF-F1", "WF-F2", "WF-F4"}),
    "uc": frozenset({"UC-F1", "UC-F2", "UC-F3", "UC-F5", "UC-F7", "UC-F8"}),
}


def section_blockers_open(state: dict[str, Any], section_id: str) -> bool:
    """Return True if the section still has open blocker flags."""
    flag_key = SECTION_FLAG_KEYS.get(section_id)
    if not flag_key:
        return True
    section_flags = state.get("flags", {}).get(flag_key, {})
    warnings = WARNING_FLAGS.get(flag_key, frozenset())
    for flag_id, info in section_flags.items():
        if flag_id in warnings:
            continue
        status = str(info.get("status", "")).upper()
        if status in BLOCKER_STATUSES:
            return True
    return False


def section_is_complete(state: dict[str, Any], section_id: str) -> bool:
    """Section is complete when every required blocker is present and PASS.

    Warnings (see WARNING_FLAGS) never grant or deny completion. A missing
    blocker — including BR-F4 still PENDING_SEMANTIC — is incomplete.
    """
    flag_key = SECTION_FLAG_KEYS.get(section_id)
    if not flag_key:
        return False
    section_flags = state.get("flags", {}).get(flag_key, {})
    if not section_flags:
        return False
    required = REQUIRED_BLOCKERS.get(flag_key, frozenset())
    for flag_id in required:
        info = section_flags.get(flag_id)
        if not info:
            return False
        status = str(info.get("status", "")).upper()
        if status != PASS:
            return False
    return not section_blockers_open(state, section_id)


def prerequisite_sections(section_id: str) -> tuple[str, ...]:
    """Return prior Tier-1 sections that must be complete before opening section_id."""
    if section_id not in TIER1_SECTIONS:
        return ()
    idx = TIER1_SECTIONS.index(section_id)
    return TIER1_SECTIONS[:idx]


def can_access_section(state: dict[str, Any], section_id: str) -> tuple[bool, str | None]:
    """Check sequential gate. Returns (allowed, reason_if_denied)."""
    for prior in prerequisite_sections(section_id):
        if not section_is_complete(state, prior):
            return False, prior
    return True, None


def mark_downstream_needs_review(state: dict[str, Any], edited_section: str) -> None:
    """Mark artifacts that depend on an edited section for a fresh review."""
    dependents = {
        SECTION_FEATURE_DEFINITION: (
            SECTION_BUSINESS_RULES,
            SECTION_WORKFLOW,
            SECTION_USE_CASES,
            "bpmn_reference",
            "ui_touchpoints",
        ),
        SECTION_BUSINESS_RULES: (
            SECTION_WORKFLOW,
            SECTION_USE_CASES,
            "bpmn_reference",
            "ui_touchpoints",
        ),
        SECTION_WORKFLOW: (SECTION_USE_CASES, "bpmn_reference", "ui_touchpoints"),
        SECTION_USE_CASES: ("ui_touchpoints",),
    }
    affected = dependents.get(edited_section, ())
    if not affected:
        return
    sec_status = dict(state.get("sections_status", {}))
    for downstream in affected:
        artifact_exists = bool((state.get("artifacts") or {}).get(downstream))
        if sec_status.get(downstream) in {"completed", "in_progress"} or artifact_exists:
            sec_status[downstream] = "needs_review"
    state["sections_status"] = sec_status


def record_package_change_review(state: dict[str, Any], edited_section: str) -> None:
    """Run deterministic cross-section checks after an artifact has changed."""
    from agents.sub_graph.validation_agent.checks import run_cross_section_checks
    from agents.sub_graph.validation_agent.logic import run_schema_check

    # An earlier VA run may have left a frozen payload in state. Review the
    # freshly merged artifacts, never that stale validation snapshot.
    review_state = {
        key: deepcopy(state.get(key))
        for key in (
            "ticket_type",
            "project_id",
            "session_id",
            "feature_id",
            "feature_title",
            "artifacts",
            "sections_status",
            "open_questions",
            "assumptions",
            "flags",
            "feature_status",
        )
    }
    review_state.pop("_va_payload", None)
    schema_blocked = run_schema_check(review_state)
    failed, warnings, passed = run_cross_section_checks(review_state)
    if schema_blocked:
        failed = list(schema_blocked.get("failed_checks") or []) + failed
    for question in state.get("open_questions") or []:
        critical_open = (
            str(question.get("severity") or "").lower() == "critical"
            and str(question.get("status") or "open").lower() != "resolved"
        )
        sync_pending = question.get("sync_status") in {"pending", "failed"}
        if critical_open:
            warnings.append(
                {
                    "check_id": "OQ-GATE",
                    "name": "Open Question chưa trả lời",
                    "detail": f"{question.get('id') or 'OQ'} chưa được chốt: {question.get('question') or ''}",
                    "suggestion": "Đây là thông tin tham khảo; Validate không bị chặn bởi Open Questions.",
                }
            )
        elif sync_pending:
            warnings.append(
                {
                    "check_id": "OQ-SYNC",
                    "name": "Open Question sync pending",
                    "detail": f"{question.get('id') or 'OQ'} đã có câu trả lời nhưng artifact liên quan chưa xác nhận đồng bộ.",
                    "suggestion": "Validate sẽ rà các artifact hiện có; xem cảnh báo này trước khi bàn giao Designer.",
                }
            )
    for section, status in (state.get("sections_status") or {}).items():
        if status == "needs_review" and section not in TIER1_SECTIONS:
            failed.append(
                {
                    "check_id": "IMPACT-REVIEW",
                    "name": "Dependent artifact needs review",
                    "detail": f"{section} bị ảnh hưởng bởi thay đổi nhưng chưa được đồng bộ/rà soát lại.",
                    "affected_sections": [section],
                    "suggestion": "Cập nhật hoặc tạo lại artifact phụ thuộc, sau đó xác nhận trạng thái review đã hoàn tất.",
                }
            )
    if not failed:
        statuses = dict(state.get("sections_status") or {})
        for section, status in statuses.items():
            if status == "needs_review" and section in TIER1_SECTIONS:
                statuses[section] = "completed"
        state["sections_status"] = statuses
    state["_ba_change_review"] = {
        "edited_section": edited_section,
        "turn": state.get("current_turn"),
        "status": "needs_fixes" if failed else "ready_for_user_validate",
        "failed_checks": failed,
        "warnings": warnings,
        "passed_checks": passed,
        "sections_needing_review": [
            section
            for section, status in (state.get("sections_status") or {}).items()
            if status == "needs_review"
        ],
    }


def has_critical_open_oq(state: dict[str, Any]) -> bool:
    oqs = state.get("open_questions", [])
    return any(
        str(oq.get("severity") or "").lower() == "critical"
        and (
            oq.get("status", "open") != "resolved"
        )
        for oq in oqs
    )


def all_required_sections_complete(state: dict[str, Any]) -> bool:
    statuses = state.get("sections_status") or {}
    return all(
        section_is_complete(state, section_id)
        or statuses.get(section_id) in {"completed", "needs_review"}
        for section_id in TIER1_SECTIONS
    )


def can_proceed_to_validation(state: dict[str, Any]) -> bool:
    """The Validate button depends only on the four required BA sections.

    Open Questions and Assumptions are supporting context, not completion
    gates. Validation can still report issues found in the actual artifacts.

    Wiki updates over time, so this stays true after VALIDATED / VALIDATION_FAILED
    / EXPORTED as long as the four required BA sections remain complete. Status
    EXPORTED no longer permanently blocks Validate.
    """
    return all_required_sections_complete(state)


def compute_feature_status_transition(state: dict[str, Any]) -> str:
    """Derive feature_status from section + validation state."""
    current = state.get("feature_status", "DRAFT")
    if current in {"VALIDATED", "VALIDATION_FAILED", "EXPORTED"}:
        return current
    if current == "DRAFT" and state.get("current_turn", 0) > 0:
        current = "IN_PROGRESS"
    if can_proceed_to_validation(state):
        if current in {"IN_PROGRESS", "DRAFT"}:
            return "PENDING_VALIDATION"
    if current == "PENDING_VALIDATION" and not can_proceed_to_validation(state):
        return "IN_PROGRESS"
    return current or "IN_PROGRESS"


def sync_sections_status_from_flags(state: dict[str, Any]) -> None:
    """Keep sections_status aligned with flag evaluation.

    Rules:
    - complete → completed
    - already needs_review → keep
    - active_section OR has any flags → in_progress
    - else → not_started
    """
    active = state.get(STATE_ACTIVE_SECTION)
    sec_status = dict(state.get("sections_status", {}))
    flags_root = state.get("flags", {})

    for section_id in TIER1_SECTIONS:
        prev = sec_status.get(section_id)
        if prev == "needs_review":
            continue
        if section_is_complete(state, section_id):
            sec_status[section_id] = "completed"
            continue

        flag_key = SECTION_FLAG_KEYS.get(section_id, "")
        has_flags = bool(flags_root.get(flag_key))
        if section_id == active or has_flags:
            sec_status[section_id] = "in_progress"
        else:
            sec_status[section_id] = "not_started"

    state["sections_status"] = sec_status
    state["feature_status"] = compute_feature_status_transition(state)

    # Per-section: current active section blockers are clear (not package-level).
    current = active or SECTION_FEATURE_DEFINITION
    state["section_completable"] = section_is_complete(state, current)
    state["can_proceed_to_validation"] = can_proceed_to_validation(state)
