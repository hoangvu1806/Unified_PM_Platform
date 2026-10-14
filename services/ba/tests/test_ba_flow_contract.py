"""Contract tests for BA sequential flow, gate, merge, flags, author filter."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.ba_agent.constants import (
    AUTHOR_FD_DISCUSSION,
    ROUTE_BR,
    ROUTE_LOCKED,
    SECTION_BUSINESS_RULES,
    SECTION_FEATURE_DEFINITION,
    SECTION_LABELS,
    SECTION_USE_CASES,
    SECTION_WORKFLOW,
    STATE_ACTIVE_SECTION,
    STATE_TICKET_TYPE,
    TICKET_NEW_FEATURE,
)
from agents.ba_agent.router import route_ba_turn
from agents.ba_agent.section_gate import (
    can_access_section,
    can_proceed_to_validation,
    has_critical_open_oq,
    section_is_complete,
    sync_sections_status_from_flags,
)
from agents.sub_graph.feature_definition.schemas import FeatureDefinitionData
from agents.sub_graph.use_cases.merge import (
    check_uc_flags_logic,
    is_user_story_row_complete,
    merge_use_cases,
)
from agents.sub_graph.use_cases.schemas import AcceptanceCriterion, UseCaseItem, UseCasesData
from agents.sub_graph.workflow.nodes.flags_checker.logic import check_wf_flags_logic
from managers.artifact.artifact_manager import canonicalize_actor, merge_feature_definition_data
from managers.service.state_helpers import is_user_facing_author


def _fd_complete_flags() -> dict:
    return {
        "FD-F1": {"status": "PASS"},
        "FD-F2": {"status": "PASS"},
        "FD-F3": {"status": "PASS"},
        "FD-F4": {"status": "WARNING"},
        "FD-F5": {"status": "PASS"},
    }


def test_fd_complete_unlocks_br_access():
    state = {
        STATE_ACTIVE_SECTION: SECTION_FEATURE_DEFINITION,
        "flags": {"fd": _fd_complete_flags()},
        "sections_status": {},
        "current_turn": 1,
        "feature_status": "IN_PROGRESS",
    }
    sync_sections_status_from_flags(state)
    assert section_is_complete(state, SECTION_FEATURE_DEFINITION)
    assert state["section_completable"] is True
    assert state["sections_status"][SECTION_FEATURE_DEFINITION] == "completed"
    assert state["sections_status"][SECTION_BUSINESS_RULES] == "not_started"
    allowed, _ = can_access_section(state, SECTION_BUSINESS_RULES)
    assert allowed
    assert can_proceed_to_validation(state) is False


def test_incomplete_fd_locks_br():
    state = {
        STATE_TICKET_TYPE: TICKET_NEW_FEATURE,
        STATE_ACTIVE_SECTION: SECTION_BUSINESS_RULES,
        "flags": {"fd": {"FD-F1": {"status": "MISSING_VALUE"}}},
    }
    ctx = MagicMock()
    ctx.state = state
    ctx.route = None
    part = MagicMock()
    part.text = "hello"
    ctx.user_content.parts = [part]
    route_ba_turn(ctx)
    assert ctx.route == ROUTE_LOCKED


def test_router_br_when_fd_complete():
    state = {
        STATE_TICKET_TYPE: TICKET_NEW_FEATURE,
        STATE_ACTIVE_SECTION: SECTION_BUSINESS_RULES,
        "flags": {"fd": _fd_complete_flags()},
    }
    ctx = MagicMock()
    ctx.state = state
    ctx.route = None
    part = MagicMock()
    part.text = "hello"
    ctx.user_content.parts = [part]
    route_ba_turn(ctx)
    assert ctx.route == ROUTE_BR


def test_sync_does_not_mark_unstarted_in_progress():
    state = {
        STATE_ACTIVE_SECTION: SECTION_FEATURE_DEFINITION,
        "flags": {"fd": {"FD-F1": {"status": "MISSING_VALUE"}}},
        "sections_status": {},
        "current_turn": 1,
    }
    sync_sections_status_from_flags(state)
    assert state["sections_status"][SECTION_FEATURE_DEFINITION] == "in_progress"
    assert state["sections_status"][SECTION_BUSINESS_RULES] == "not_started"
    assert state["sections_status"][SECTION_WORKFLOW] == "not_started"
    assert state["section_completable"] is False


def _all_tier1_pass_flags() -> dict:
    return {
        "fd": {
            "FD-F1": {"status": "PASS"},
            "FD-F2": {"status": "PASS"},
            "FD-F3": {"status": "PASS"},
            "FD-F5": {"status": "PASS"},
        },
        "br": {"BR-F1": {"status": "PASS"}, "BR-F4": {"status": "PASS"}},
        "wf": {
            "WF-F1": {"status": "PASS"},
            "WF-F2": {"status": "PASS"},
            "WF-F4": {"status": "PASS"},
        },
        "uc": {
            "UC-F1": {"status": "PASS"},
            "UC-F2": {"status": "PASS"},
            "UC-F3": {"status": "PASS"},
            "UC-F5": {"status": "PASS"},
            "UC-F7": {"status": "PASS"},
            "UC-F8": {"status": "PASS"},
        },
    }


def test_critical_open_oq_blocks_validation_until_resolved():
    state = {
        "flags": _all_tier1_pass_flags(),
        "feature_status": "IN_PROGRESS",
        "current_turn": 4,
        "open_questions": [
            {
                "id": "OQ-001",
                "severity": "critical",
                "status": "open",
                "question": "Ngưỡng?",
            }
        ],
    }
    assert has_critical_open_oq(state) is True
    assert can_proceed_to_validation(state) is False
    state["open_questions"][0]["status"] = "resolved"
    state["open_questions"][0]["answer"] = "50 triệu VND"
    assert has_critical_open_oq(state) is False
    assert can_proceed_to_validation(state) is True


def test_exported_still_allows_validate_when_group1_clear():
    state = {
        "flags": _all_tier1_pass_flags(),
        "feature_status": "EXPORTED",
        "open_questions": [],
    }
    assert can_proceed_to_validation(state) is True
    state["open_questions"] = [
        {"id": "OQ-001", "severity": "critical", "status": "open", "question": "Ngưỡng?"}
    ]
    assert can_proceed_to_validation(state) is False


def test_section_completable_vs_package_validation():
    state = {
        STATE_ACTIVE_SECTION: SECTION_FEATURE_DEFINITION,
        "flags": {"fd": _fd_complete_flags()},
        "current_turn": 2,
        "feature_status": "IN_PROGRESS",
        "open_questions": [],
    }
    sync_sections_status_from_flags(state)
    assert state["section_completable"] is True
    assert state["can_proceed_to_validation"] is False
    assert can_proceed_to_validation(state) is False


def test_fd_merge_appends_actors_without_wipe():
    current = FeatureDefinitionData(
        goal="Sell flags online before 2/9",
        actors=["ACT-KHACH: buyer", "ACT-ADMIN: admin"],
        scope_in=["catalog"],
        scope_out=["ads"],
    )
    delta = FeatureDefinitionData(
        goal=None,
        actors=["ACT-SHIPPER: shipper"],
        scope_in=["checkout"],
        scope_out=None,
    )
    merged = merge_feature_definition_data(current, delta)
    assert merged.goal == "Sell flags online before 2/9"
    assert "ACT-KHACH: buyer" in merged.actors
    assert "ACT-SHIPPER: shipper" in merged.actors
    assert "catalog" in merged.scope_in
    assert "checkout" in merged.scope_in
    assert merged.scope_out == ["ads"]


def test_canonicalize_actor_and_uc_match():
    assert canonicalize_actor("ACT-KHACH: người mua") == "ACT-KHACH: người mua"
    assert canonicalize_actor("Customer").startswith("ACT-CUSTOMER:")

    ctx = MagicMock()
    ctx.state = {
        "artifacts": {
            "feature_definition": {
                "actors": [
                    canonicalize_actor("ACT-KHACH: buyer"),
                    canonicalize_actor("ACT-ADMIN: admin"),
                ]
            },
            "use_cases": [
                {
                    "id": "US-01",
                    "actor_id": "ACT-KHACH",
                    "statement": "Là khách, tôi muốn đặt cờ để trang trí",
                    "rule_ids": ["BR-01"],
                    "acceptance_criteria": [
                        {"given": "g", "when": "w", "then": "t"}
                    ],
                }
            ],
            "business_rules": [{"id": "BR-01", "statement": "x", "source": "PO"}],
        },
        "flags": {},
        "active_section": "use_cases",
    }
    flags = check_uc_flags_logic(ctx)
    assert flags["UC-F3"]["status"] == "PASS"


def test_br_semantic_flags_pending_when_enough_rules():
    from agents.sub_graph.business_rules.nodes.flags_checker.logic import check_br_flags_logic

    ctx = MagicMock()
    ctx.state = {
        "artifacts": {
            "business_rules": [
                {"id": "BR-01", "statement": "Khi A thì B", "source": "PO"},
                {"id": "BR-02", "statement": "Khi C thì D", "source": "Policy"},
            ]
        },
        "flags": {},
        "active_section": "business_rules",
        "sections_status": {},
    }
    flags = check_br_flags_logic(ctx)
    assert flags["BR-F1"]["status"] == "PASS"
    assert flags["BR-F2"]["status"] == "PASS"
    assert flags["BR-F3"]["status"] == "PENDING_SEMANTIC"
    assert flags["BR-F4"]["status"] == "PENDING_SEMANTIC"
    assert flags["BR-F5"]["status"] == "PENDING_SEMANTIC"
    # 2/5 PASS (F1+F2) must not COMPLETED while semantic blocker BR-F4 is pending.
    assert section_is_complete(ctx.state, SECTION_BUSINESS_RULES) is False
    assert ctx.state["sections_status"][SECTION_BUSINESS_RULES] != "completed"


def test_br_f4_sticky_pass():
    from agents.sub_graph.business_rules.nodes.flags_checker.logic import check_br_flags_logic

    ctx = MagicMock()
    ctx.state = {
        "artifacts": {
            "business_rules": [
                {"id": "BR-01", "statement": "Khi A thì B", "source": "PO"},
                {"id": "BR-02", "statement": "Khi C thì D", "source": "Policy"},
            ]
        },
        "flags": {"br": {"BR-F4": {"status": "PASS"}}},
        "active_section": "business_rules",
        "sections_status": {},
    }
    flags = check_br_flags_logic(ctx)
    assert flags["BR-F4"]["status"] == "PASS"
    assert section_is_complete(ctx.state, SECTION_BUSINESS_RULES) is True
    assert ctx.state["sections_status"][SECTION_BUSINESS_RULES] == "completed"


def test_br_warnings_do_not_grant_or_fake_completion():
    """BR completes on blockers F1+F4 PASS; warnings may stay open (2/5 PASS)."""
    warnings_open = {
        "BR-F1": {"status": "PASS"},
        "BR-F2": {"status": "WARNING"},
        "BR-F3": {"status": "PENDING_SEMANTIC"},
        "BR-F4": {"status": "PASS"},
        "BR-F5": {"status": "PENDING_SEMANTIC"},
    }
    state = {"flags": {"br": warnings_open}, "sections_status": {}}
    assert section_is_complete(state, SECTION_BUSINESS_RULES) is True
    sync_sections_status_from_flags(state)
    assert state["sections_status"][SECTION_BUSINESS_RULES] == "completed"

    missing_f4 = {
        "BR-F1": {"status": "PASS"},
        "BR-F2": {"status": "PASS"},
        "BR-F3": {"status": "PENDING_SEMANTIC"},
        "BR-F5": {"status": "PENDING_SEMANTIC"},
    }
    assert section_is_complete({"flags": {"br": missing_f4}}, SECTION_BUSINESS_RULES) is False
    pending_f4 = dict(missing_f4, **{"BR-F4": {"status": "PENDING_SEMANTIC"}})
    assert section_is_complete({"flags": {"br": pending_f4}}, SECTION_BUSINESS_RULES) is False
    not_yet_f4 = dict(missing_f4, **{"BR-F4": {"status": "NOT_YET_REASONABLE"}})
    assert section_is_complete({"flags": {"br": not_yet_f4}}, SECTION_BUSINESS_RULES) is False
    warning_f4 = dict(missing_f4, **{"BR-F4": {"status": "WARNING"}})
    assert section_is_complete({"flags": {"br": warning_f4}}, SECTION_BUSINESS_RULES) is False


def test_uc_f5_f8_pending_semantic():
    ctx = MagicMock()
    ctx.state = {
        "artifacts": {
            "feature_definition": {
                "actors": ["ACT-A: a", "ACT-B: b"],
            },
            "business_rules": [{"id": "BR-01", "statement": "x", "source": "PO"}],
            "use_cases": [
                {
                    "id": "US-01",
                    "actor_id": "ACT-A",
                    "statement": "Là A, tôi muốn x để y",
                    "rule_ids": ["BR-01"],
                    "acceptance_criteria": [
                        {"given": "g", "when": "w", "then": "t"}
                    ],
                },
                {
                    "id": "US-02",
                    "actor_id": "ACT-B",
                    "statement": "Là B, tôi muốn p để q",
                    "rule_ids": ["BR-01"],
                    "acceptance_criteria": [
                        {"given": "g2", "when": "w2", "then": "t2"}
                    ],
                },
            ],
        },
        "flags": {},
        "active_section": "use_cases",
        "sections_status": {},
    }
    flags = check_uc_flags_logic(ctx)
    assert flags["UC-F1"]["status"] == "PASS"
    assert flags["UC-F5"]["status"] == "PENDING_SEMANTIC"
    assert flags["UC-F6"]["status"] == "PASS"
    assert flags["UC-F8"]["status"] == "PENDING_SEMANTIC"


def test_wf_f1_counts_numbered_main_flow_not_only_tables():
    from agents.sub_graph.workflow.nodes.flags_checker.logic import _count_main_flow_steps

    numbered = """
## Main Flow
1. ACT-KE-TOAN tạo phiếu chi
2. Hệ thống kiểm tra BR-01
3. ACT-PO-PURCHASE-OFFICER phê duyệt
4. Hệ thống ghi sổ

## Exception Flows
- Thiếu chứng từ → Nháp
- Từ chối → End

## End States
- Đã duyệt
"""
    assert _count_main_flow_steps(numbered) == 4
    ctx = MagicMock()
    ctx.state = {
        "artifacts": {"workflow": {"workflow_md_content": numbered}},
        "flags": {},
        "active_section": "workflow",
        "sections_status": {},
    }
    flags = check_wf_flags_logic(ctx)
    assert flags["WF-F1"]["status"] == "PASS"
    assert flags["WF-F2"]["status"] == "PENDING_SEMANTIC"


def test_wf_f2_pending_with_main_flow():
    content = """
## Main Flow
| Step | Actor | Action |
|------|-------|--------|
| 1 | ACT-A | Start |
| 2 | ACT-B | Mid |
| 3 | ACT-A | End |

## Exception Flows
timeout

## End States
Done
"""
    ctx = MagicMock()
    ctx.state = {
        "artifacts": {"workflow": {"workflow_md_content": content}},
        "flags": {},
        "active_section": "workflow",
        "sections_status": {},
    }
    flags = check_wf_flags_logic(ctx)
    assert flags["WF-F1"]["status"] == "PASS"
    assert flags["WF-F2"]["status"] == "PENDING_SEMANTIC"
    assert flags["WF-F4"]["status"] == "PENDING_SEMANTIC"
    content = """
## Main Flow
| Step | Actor | Action |
|------|-------|--------|
| 1 | ACT-A | Start |
| 2 | ACT-B | Mid |
| 3 | ACT-A | End |

## Exception Flows
E1 timeout

## End States
Done
"""
    ctx = MagicMock()
    ctx.state = {
        "artifacts": {"workflow": {"workflow_md_content": content}},
        "flags": {
            "wf": {
                "WF-F2": {"status": "PASS"},
                "WF-F4": {"status": "PASS"},
            }
        },
        "active_section": "workflow",
        "sections_status": {},
    }
    flags = check_wf_flags_logic(ctx)
    assert flags["WF-F4"]["status"] == "PASS"
    flags2 = check_wf_flags_logic(ctx)
    assert flags2["WF-F4"]["status"] == "PASS"


def test_history_author_filter():
    assert is_user_facing_author(AUTHOR_FD_DISCUSSION) is True
    assert is_user_facing_author("va_discuss") is True
    assert is_user_facing_author("va_explain") is True
    assert is_user_facing_author("va_report") is True
    assert is_user_facing_author("fd_extractor") is False
    assert is_user_facing_author("fd_flags_checker") is False
    assert is_user_facing_author(None) is False


def test_apply_semantic_flag_evaluations_no_tools():
    from agents.sub_graph.shared.semantic_flags import apply_semantic_flag_evaluations

    state = {
        "flags": {
            "fd": {
                "FD-F1": {"status": "PENDING_SEMANTIC", "name": "Goal"},
                "FD-F2": {"status": "PASS"},
            }
        },
        "active_section": "feature_definition",
        "sections_status": {},
        "current_turn": 1,
    }
    n = apply_semantic_flag_evaluations(
        state,
        "fd",
        '{"evaluations":[{"flag_id":"FD-F1","status":"PASS","detail":null}]}',
    )
    assert n == 1
    assert state["flags"]["fd"]["FD-F1"]["status"] == "PASS"


def test_empty_evaluation_response_is_valid_schema():
    from agents.sub_graph.shared.semantic_flags import (
        EMPTY_EVALUATION_JSON,
        SemanticFlagsEvaluation,
        empty_evaluation_response,
    )

    resp = empty_evaluation_response()
    text = resp.content.parts[0].text
    assert text == EMPTY_EVALUATION_JSON
    parsed = SemanticFlagsEvaluation.model_validate_json(text)
    assert parsed.evaluations == []


def test_section_label_user_stories_keeps_use_cases_id():
    assert SECTION_USE_CASES == "use_cases"
    assert SECTION_LABELS[SECTION_USE_CASES] == "User Stories"


def test_merge_one_active_story_lock():
    incomplete = {
        "id": "US-01",
        "actor_id": "ACT-A",
        "statement": "Là A, tôi muốn x để y",
        "rule_ids": [],
        "acceptance_criteria": [],
    }
    delta_two = UseCasesData(
        use_cases=[
            UseCaseItem(
                id="US-01",
                actor_id="ACT-A",
                statement="Là A, tôi muốn x để y",
                acceptance_criteria=[],
            ),
            UseCaseItem(
                id="US-02",
                actor_id="ACT-B",
                statement="Là B, tôi muốn p để q",
                acceptance_criteria=[
                    AcceptanceCriterion(given="g", when="w", then="t")
                ],
            ),
        ]
    )
    merged, active = merge_use_cases(
        [incomplete], delta_two, active_user_story_id="US-01"
    )
    assert active == "US-01"
    assert len(merged) == 1
    assert not is_user_story_row_complete(merged[0])

    # Complete active story, then unlock US-02.
    complete_delta = UseCasesData(
        use_cases=[
            UseCaseItem(
                id="US-01",
                actor_id="ACT-A",
                statement="Là A, tôi muốn x để y",
                acceptance_criteria=[
                    AcceptanceCriterion(given="g", when="w", then="t")
                ],
            )
        ]
    )
    merged, active = merge_use_cases(
        merged, complete_delta, active_user_story_id="US-01"
    )
    assert is_user_story_row_complete(merged[0])
    assert active == "US-01"

    next_delta = UseCasesData(
        use_cases=[
            UseCaseItem(
                id="US-02",
                actor_id="ACT-B",
                statement="Là B, tôi muốn p để q",
                acceptance_criteria=[
                    AcceptanceCriterion(given="g2", when="w2", then="t2")
                ],
            )
        ]
    )
    merged, active = merge_use_cases(
        merged, next_delta, active_user_story_id="US-01"
    )
    assert len(merged) == 2
    assert active == "US-02"


def test_uc_f1_still_min_one_story():
    ctx = MagicMock()
    ctx.state = {
        "artifacts": {
            "feature_definition": {"actors": ["ACT-A: a"]},
            "business_rules": [],
            "use_cases": [
                {
                    "id": "US-01",
                    "actor_id": "ACT-A",
                    "statement": "Là A, tôi muốn x để y",
                    "rule_ids": [],
                    "acceptance_criteria": [
                        {"given": "g", "when": "w", "then": "t"}
                    ],
                }
            ],
        },
        "flags": {},
        "active_section": "use_cases",
        "sections_status": {},
        "active_user_story_id": "US-01",
    }
    flags = check_uc_flags_logic(ctx)
    assert flags["UC-F1"]["status"] == "PASS"
    assert ctx.state["active_user_story_id"] == "US-01"
