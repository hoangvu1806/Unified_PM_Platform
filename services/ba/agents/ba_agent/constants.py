"""Canonical session-state keys and graph routes for the unified BA Agent."""

from __future__ import annotations

from typing import Final

TICKET_NEW_FEATURE: Final = "NEW_FEATURE"
TICKET_FEATURE_ENHANCEMENT: Final = "FEATURE_ENHANCEMENT"
TICKET_BUG_FIX_LOG: Final = "BUG_FIX_LOG"
TICKET_PROCESS_OPTIMIZATION: Final = "PROCESS_OPTIMIZATION"

SUPPORTED_TICKET_TYPES: Final[frozenset[str]] = frozenset(
    {
        TICKET_NEW_FEATURE,
        TICKET_FEATURE_ENHANCEMENT,
        TICKET_BUG_FIX_LOG,
        TICKET_PROCESS_OPTIMIZATION,
    }
)

IMPLEMENTED_TICKET_TYPES: Final[frozenset[str]] = frozenset({TICKET_NEW_FEATURE})

SECTION_FEATURE_DEFINITION: Final = "feature_definition"
SECTION_BUSINESS_RULES: Final = "business_rules"
SECTION_WORKFLOW: Final = "workflow"
SECTION_USE_CASES: Final = "use_cases"
SECTION_VALIDATION: Final = "validation"
SECTION_BPMN: Final = "bpmn_reference"
SECTION_UI_TOUCHPOINTS: Final = "ui_touchpoints"

TIER1_SECTIONS: Final[tuple[str, ...]] = (
    SECTION_FEATURE_DEFINITION,
    SECTION_BUSINESS_RULES,
    SECTION_WORKFLOW,
    SECTION_USE_CASES,
)

IMPLEMENTED_SECTIONS: Final[frozenset[str]] = frozenset(TIER1_SECTIONS)

DEFAULT_SECTION: Final = SECTION_FEATURE_DEFINITION
DEFAULT_TICKET_TYPE: Final = TICKET_NEW_FEATURE

STATE_TICKET_TYPE: Final = "ticket_type"
STATE_ACTIVE_SECTION: Final = "active_section"
STATE_ACTIVE_USER_STORY_ID: Final = "active_user_story_id"
STATE_ARTIFACTS: Final = "artifacts"
STATE_FLAGS: Final = "flags"
STATE_OPEN_QUESTIONS: Final = "open_questions"
STATE_ASSUMPTIONS: Final = "assumptions"
STATE_SECTIONS_STATUS: Final = "sections_status"
STATE_FEATURE_STATUS: Final = "feature_status"
STATE_PROJECT_ID: Final = "project_id"
STATE_VALIDATE_ACTION: Final = "_validate_action"

ROUTE_FD: Final = "fd"
ROUTE_BR: Final = "br"
ROUTE_WF: Final = "wf"
ROUTE_UC: Final = "uc"
ROUTE_VALIDATE: Final = "validate"
ROUTE_LOCKED: Final = "locked"
ROUTE_STUB: Final = "stub"

AUTHOR_FD_DISCUSSION: Final = "fd_discussion"
AUTHOR_BR_DISCUSSION: Final = "br_discussion"
AUTHOR_WF_DISCUSSION: Final = "wf_discussion"
AUTHOR_UC_DISCUSSION: Final = "uc_discussion"
AUTHOR_BA_NOT_READY: Final = "ba_not_ready"
AUTHOR_BA_LOCKED: Final = "ba_section_locked"
AUTHOR_VA_REPORT: Final = "va_report"
AUTHOR_VA_DISCUSS: Final = "va_discuss"
AUTHOR_VA_EXPLAIN: Final = "va_explain"

VA_CHAT_AUTHORS: Final[frozenset[str]] = frozenset(
    {
        AUTHOR_VA_REPORT,
        AUTHOR_VA_DISCUSS,
        AUTHOR_VA_EXPLAIN,
    }
)

USER_FACING_AUTHORS: Final[frozenset[str]] = frozenset(
    {
        AUTHOR_FD_DISCUSSION,
        AUTHOR_BR_DISCUSSION,
        AUTHOR_WF_DISCUSSION,
        AUTHOR_UC_DISCUSSION,
        AUTHOR_BA_NOT_READY,
        AUTHOR_BA_LOCKED,
        AUTHOR_VA_REPORT,
        AUTHOR_VA_DISCUSS,
        AUTHOR_VA_EXPLAIN,
    }
)

SECTION_TO_ROUTE: Final[dict[str, str]] = {
    SECTION_FEATURE_DEFINITION: ROUTE_FD,
    SECTION_BUSINESS_RULES: ROUTE_BR,
    SECTION_WORKFLOW: ROUTE_WF,
    SECTION_USE_CASES: ROUTE_UC,
}

SECTION_DISCUSSION_AUTHOR: Final[dict[str, str]] = {
    SECTION_FEATURE_DEFINITION: AUTHOR_FD_DISCUSSION,
    SECTION_BUSINESS_RULES: AUTHOR_BR_DISCUSSION,
    SECTION_WORKFLOW: AUTHOR_WF_DISCUSSION,
    SECTION_USE_CASES: AUTHOR_UC_DISCUSSION,
    SECTION_VALIDATION: AUTHOR_VA_DISCUSS,
}

SECTION_LABELS: Final[dict[str, str]] = {
    SECTION_FEATURE_DEFINITION: "Feature Definition",
    SECTION_BUSINESS_RULES: "Business Rules",
    SECTION_WORKFLOW: "Workflow",
    SECTION_USE_CASES: "User Stories",
}

TICKET_LABELS: Final[dict[str, str]] = {
    TICKET_NEW_FEATURE: "New Feature",
    TICKET_FEATURE_ENHANCEMENT: "Feature Enhancement",
    TICKET_BUG_FIX_LOG: "Bug Fix Log",
    TICKET_PROCESS_OPTIMIZATION: "Process Optimization",
}

VALIDATE_MESSAGE_PREFIX: Final = "[VALIDATE]"
