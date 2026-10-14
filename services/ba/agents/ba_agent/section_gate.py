"""Sequential section gating for NEW_FEATURE ticket type."""

from __future__ import annotations

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
    """When user edits an earlier section, mark downstream sections stale."""
    if edited_section not in TIER1_SECTIONS:
        return
    idx = TIER1_SECTIONS.index(edited_section)
    sec_status = dict(state.get("sections_status", {}))
    for downstream in TIER1_SECTIONS[idx + 1 :]:
        if sec_status.get(downstream) in {"completed", "in_progress"}:
            sec_status[downstream] = "needs_review"
    state["sections_status"] = sec_status


def has_critical_open_oq(state: dict[str, Any]) -> bool:
    oqs = state.get("open_questions", [])
    return any(
        oq.get("status", "open") == "open" and oq.get("severity") == "critical"
        for oq in oqs
    )


def all_required_sections_complete(state: dict[str, Any]) -> bool:
    return all(section_is_complete(state, sec) for sec in TIER1_SECTIONS)


def can_proceed_to_validation(state: dict[str, Any]) -> bool:
    """Package-level: all Tier-1 complete and no critical open OQs.

    Wiki updates over time, so this stays true after VALIDATED / VALIDATION_FAILED
    / EXPORTED as long as Group 1 and critical OQs still clear. Status EXPORTED
    no longer permanently blocks Validate.
    """
    return all_required_sections_complete(state) and not has_critical_open_oq(state)


def compute_feature_status_transition(state: dict[str, Any]) -> str:
    """Derive feature_status from section + validation state."""
    current = state.get("feature_status", "DRAFT")
    if current in {"VALIDATED", "VALIDATION_FAILED", "EXPORTED"}:
        return current
    if current == "DRAFT" and state.get("current_turn", 0) > 0:
        current = "IN_PROGRESS"
    if all_required_sections_complete(state) and not has_critical_open_oq(state):
        if current in {"IN_PROGRESS", "DRAFT"}:
            return "PENDING_VALIDATION"
    if current == "PENDING_VALIDATION" and not all_required_sections_complete(state):
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
        if section_is_complete(state, section_id):
            sec_status[section_id] = "completed"
            continue

        prev = sec_status.get(section_id)
        if prev == "needs_review":
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
