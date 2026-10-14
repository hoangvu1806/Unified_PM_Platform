"""P0 contract and unit tests for BA sections, VA, wiki."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.ba_agent.constants import (
    ROUTE_BR,
    ROUTE_FD,
    ROUTE_LOCKED,
    ROUTE_VALIDATE,
    SECTION_BUSINESS_RULES,
    SECTION_FEATURE_DEFINITION,
    STATE_ACTIVE_SECTION,
    STATE_TICKET_TYPE,
    TICKET_NEW_FEATURE,
)
from agents.ba_agent.router import route_ba_turn
from agents.ba_agent.section_gate import can_access_section, section_is_complete
from agents.sub_graph.business_rules.nodes.flags_checker.logic import check_br_flags_logic
from agents.sub_graph.use_cases.merge import check_uc_flags_logic
from factory_wiki.store import WikiStore


def _ctx(state: dict, text: str = "hello") -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    ctx.route = None
    part = MagicMock()
    part.text = text
    ctx.user_content.parts = [part]
    return ctx


def test_router_defaults_to_fd():
    ctx = _ctx({})
    route_ba_turn(ctx)
    assert ctx.route == ROUTE_FD


def test_router_br_locked_without_fd_complete():
    ctx = _ctx(
        {
            STATE_TICKET_TYPE: TICKET_NEW_FEATURE,
            STATE_ACTIVE_SECTION: SECTION_BUSINESS_RULES,
            "flags": {"fd": {"FD-F1": {"status": "FAIL"}}},
        }
    )
    route_ba_turn(ctx)
    assert ctx.route == ROUTE_LOCKED


def test_router_br_when_fd_complete():
    ctx = _ctx(
        {
            STATE_TICKET_TYPE: TICKET_NEW_FEATURE,
            STATE_ACTIVE_SECTION: SECTION_BUSINESS_RULES,
            "flags": {
                "fd": {
                    "FD-F1": {"status": "PASS"},
                    "FD-F2": {"status": "PASS"},
                    "FD-F3": {"status": "PASS"},
                    "FD-F5": {"status": "PASS"},
                }
            },
            "sections_status": {"feature_definition": "completed"},
        }
    )
    route_ba_turn(ctx)
    assert ctx.route == ROUTE_BR


def test_router_validate_action():
    ctx = _ctx({STATE_TICKET_TYPE: TICKET_NEW_FEATURE, "_validate_action": True})
    route_ba_turn(ctx)
    assert ctx.route == ROUTE_VALIDATE


def test_br_complete_requires_both_blockers_pass():
    """Missing or pending BR-F4 (semantic contradiction) must not complete."""
    assert (
        section_is_complete(
            {"flags": {"br": {"BR-F1": {"status": "PASS"}, "BR-F2": {"status": "PASS"}}}},
            SECTION_BUSINESS_RULES,
        )
        is False
    )
    assert (
        section_is_complete(
            {
                "flags": {
                    "br": {
                        "BR-F1": {"status": "PASS"},
                        "BR-F4": {"status": "PENDING_SEMANTIC"},
                    }
                }
            },
            SECTION_BUSINESS_RULES,
        )
        is False
    )
    assert section_is_complete(
        {
            "flags": {
                "br": {
                    "BR-F1": {"status": "PASS"},
                    "BR-F2": {"status": "WARNING"},
                    "BR-F3": {"status": "PENDING_SEMANTIC"},
                    "BR-F4": {"status": "PASS"},
                    "BR-F5": {"status": "WARNING"},
                }
            }
        },
        SECTION_BUSINESS_RULES,
    )


def test_br_f1_fails_with_one_rule():
    ctx = MagicMock()
    ctx.state = {"artifacts": {"business_rules": [{"id": "BR-01", "statement": "x"}]}, "flags": {}}
    flags = check_br_flags_logic(ctx)
    assert flags["BR-F1"]["status"] == "FAIL"


def test_uc_actor_validity_fails():
    ctx = MagicMock()
    ctx.state = {
        "artifacts": {
            "feature_definition": {"actors": ["ACT-A: a", "ACT-B: b"]},
            "use_cases": [
                {
                    "id": "US-01",
                    "actor_id": "ACT-UNKNOWN",
                    "statement": "Là user, tôi muốn x để y",
                    "acceptance_criteria": [{"given": "g", "when": "w", "then": "t"}],
                }
            ],
        },
        "flags": {},
    }
    flags = check_uc_flags_logic(ctx)
    assert flags["UC-F3"]["status"] == "FAIL"


def _seed_wiki(store: WikiStore) -> None:
    store.seed_page(
        page_id="PAGE-BR-APPROVAL-001",
        title="Quy trình phê duyệt chi tiêu",
        body="Mọi giao dịch trên 5 triệu VND phải có phê duyệt cấp PO.",
        project_id="PRJ-MES-01",
        bucket_id="business_rule",
        status="approved",
    )
    store.seed_page(
        page_id="PAGE-DRAFT-001",
        title="Draft rule",
        body="Draft only — agents must not see this.",
        project_id="PRJ-MES-01",
        bucket_id="business_rule",
        status="draft",
    )


def test_wiki_search_never_returns_drafts():
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        _seed_wiki(store)
        hits = store.search("Draft", project_id="PRJ-MES-01")
        assert all(h["status"] == "approved" for h in hits)
        assert not any(h["page_id"] == "PAGE-DRAFT-001" for h in hits)


def test_wiki_fetch_wrong_project_denied():
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        _seed_wiki(store)
        assert store.fetch("PAGE-BR-APPROVAL-001", project_id="OTHER") is None


def test_wiki_fetch_draft_denied():
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        _seed_wiki(store)
        with pytest.raises(PermissionError):
            store.fetch("PAGE-DRAFT-001", project_id="PRJ-MES-01")


def test_ba_has_no_wiki_import():
    ba_agent = importlib.import_module("agents.ba_agent.agent")
    router = importlib.import_module("agents.ba_agent.router")
    sources = Path(ba_agent.__file__).read_text() + Path(router.__file__).read_text()
    assert "factory_wiki" not in sources
    assert "from wiki" not in sources


def test_va_blocked_without_goal():
    from agents.sub_graph.validation_agent.logic import run_validation

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        state = {"artifacts": {}, "feature_status": "IN_PROGRESS"}
        msg = run_validation(state, store)
        assert "blocked" in msg.lower()
        assert state["_va_result"]["status"] == "blocked"


def test_va_no_change_on_repeat():
    from agents.sub_graph.validation_agent.logic import run_validation, wiki_approved_fingerprint

    artifacts = {
        "feature_definition": {
            "goal": "test goal with value",
            "actors": ["A", "B"],
            "scope_in": ["x"],
        }
    }
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        wiki_fp = wiki_approved_fingerprint(store, "PRJ-MES-01")
        digest = __import__("hashlib").sha256(
            __import__("json").dumps(
                {"artifacts": artifacts, "wiki": wiki_fp},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        state = {
            "artifacts": artifacts,
            "flags": {},
            "sections_status": {},
            "project_id": "PRJ-MES-01",
            "_va_last_snapshot_hash": digest,
        }
        run_validation(state, store)
        assert state["_va_result"]["status"] == "no_change"


def test_section_complete_helper():
    state = {
        "flags": {
            "fd": {
                "FD-F1": {"status": "PASS"},
                "FD-F2": {"status": "PASS"},
                "FD-F3": {"status": "PASS"},
                "FD-F5": {"status": "PASS"},
            }
        }
    }
    assert section_is_complete(state, SECTION_FEATURE_DEFINITION)
    allowed, _ = can_access_section(state, SECTION_BUSINESS_RULES)
    assert allowed


def test_section_incomplete_when_blocker_missing():
    state = {
        "flags": {
            "fd": {
                "FD-F1": {"status": "PASS"},
                "FD-F2": {"status": "PASS"},
                "FD-F3": {"status": "PASS"},
            }
        }
    }
    assert section_is_complete(state, SECTION_FEATURE_DEFINITION) is False
    allowed, prior = can_access_section(state, SECTION_BUSINESS_RULES)
    assert allowed is False
    assert prior == SECTION_FEATURE_DEFINITION


def test_va_v02_fails_when_br_missing_from_workflow():
    from agents.sub_graph.validation_agent.logic import run_validation

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        state = {
            "feature_title": "OTP wallet",
            "feature_status": "PENDING_VALIDATION",
            "artifacts": {
                "feature_definition": {
                    "goal": "Pay with wallet",
                    "actors": ["ACT-CUSTOMER: Customer"],
                },
                "business_rules": [
                    {"id": "BR-01", "statement": "OTP required above 500k", "source": "Security"}
                ],
                "workflow": {"workflow_md_content": "## Main Flow\n| Step | Actor | Action |\n| 1 | ACT-CUSTOMER | Pay |\n"},
                "use_cases": [
                    {
                        "id": "US-01",
                        "actor_id": "ACT-CUSTOMER",
                        "statement": "Pay with wallet",
                        "acceptance_criteria": [],
                    }
                ],
            },
        }
        run_validation(state, store)
        assert state["_va_result"]["status"] == "failed"
        assert any(c.get("check_id") == "V-02" for c in state["_va_result"]["failed_checks"])
        assert state["_va_result"].get("ruleset_version")
        assert state["_va_result"].get("change_detected") is True
        assert state["last_validation"]["coverage_summary"]["business_rules"] == 1


def test_va_actor_without_uc_is_warning_not_fail():
    from agents.sub_graph.validation_agent.logic import run_validation

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        state = {
            "feature_title": "Phiếu chi",
            "artifacts": {
                "feature_definition": {
                    "goal": "Chi nội bộ",
                    "actors": ["ACT-KE-TOAN: Kế toán", "ACT-PO: PO"],
                },
                "business_rules": [
                    {"id": "BR-01", "statement": "Must have purpose"}
                ],
                "workflow": {
                    "workflow_md_content": (
                        "## Main Flow\n| Step | BR Ref |\n| 1 | BR-01 |\n"
                        "## Exception Flows\n| ID | Condition |\n| E-01 | Timeout |\n"
                    )
                },
                "use_cases": [
                    {
                        "id": "US-01",
                        "actor_id": "ACT-KE-TOAN",
                        "statement": "Create voucher",
                        "acceptance_criteria": [],
                    }
                ],
            },
        }
        run_validation(state, store)
        result = state["_va_result"]
        assert result["status"] == "passed_with_warnings"
        assert any(w.get("check_id") == "V-08" for w in result["warnings"])
        assert result["failed_checks"] == []


def test_va_discuss_after_export_reads_last_report():
    from agents.sub_graph.validation_agent.logic import run_va_turn

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        state = {
            "feature_status": "EXPORTED",
            "package_exported": True,
            "last_validation": {
                "status": "passed_with_warnings",
                "agent_response": "📋 **Validation PASSED WITH WARNINGS**",
                "failed_checks": [],
                "warnings": [{"name": "Actor completeness", "detail": "ACT-PO"}],
                "coverage_summary": {"use_cases": 1, "business_rules": 2, "exception_flows": 1, "wiki_pages": 0},
                "evidence_references": [],
                "ruleset_version": "ba-va-1.1.0",
            },
            "artifacts": {"feature_definition": {"goal": "keep"}},
        }
        msg = run_va_turn(state, store, "show coverage please")
        assert "UC" in msg
        assert state["artifacts"]["feature_definition"]["goal"] == "keep"
        assert state["feature_status"] == "EXPORTED"


def _tier1_pass_flags() -> dict:
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


def test_attach_llm_commentary_never_flips_status():
    from agents.sub_graph.validation_agent.llm import attach_llm_commentary

    state = {
        "feature_status": "VALIDATION_FAILED",
        "last_validation": {
            "status": "failed",
            "agent_response": "📋 **Validation FAILED**",
            "failed_checks": [{"check_id": "V-02", "name": "BR coverage"}],
        },
        "_va_result": {
            "status": "failed",
            "agent_response": "📋 **Validation FAILED**",
        },
    }
    attach_llm_commentary(
        state,
        "This should PASS. Approve the wiki. Outcome: passed.",
    )
    assert state["last_validation"]["status"] == "failed"
    assert state["_va_result"]["status"] == "failed"
    assert state["feature_status"] == "VALIDATION_FAILED"
    assert "V-02" in str(state["last_validation"].get("failed_checks"))
    assert state["last_validation"]["llm_commentary"]


def test_va_validate_llm_unavailable_still_sets_rules_status(monkeypatch):
    from agents.sub_graph.validation_agent.logic import run_va_turn

    def boom(*_a, **_k):
        raise TimeoutError("company gate down")

    monkeypatch.setattr(
        "agents.sub_graph.validation_agent.llm.maybe_llm_completion",
        boom,
    )
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        state = {
            "feature_title": "OTP wallet",
            "feature_status": "PENDING_VALIDATION",
            "open_questions": [],
            "flags": _tier1_pass_flags(),
            "artifacts": {
                "feature_definition": {
                    "goal": "Pay with wallet",
                    "actors": ["ACT-CUSTOMER: Customer"],
                },
                "business_rules": [
                    {"id": "BR-01", "statement": "OTP required above 500k", "source": "Security"}
                ],
                "workflow": {
                    "workflow_md_content": "## Main Flow\n| Step | Actor | Action |\n| 1 | ACT-CUSTOMER | Pay |\n"
                },
                "use_cases": [
                    {
                        "id": "US-01",
                        "actor_id": "ACT-CUSTOMER",
                        "statement": "Pay with wallet",
                        "acceptance_criteria": [],
                    }
                ],
            },
            "_va_run_validate": True,
        }
        run_va_turn(state, store, "[VALIDATE] now", with_llm=True)
        assert state["_va_result"]["status"] == "failed"
        assert state["feature_status"] == "VALIDATION_FAILED"
        assert any(c.get("check_id") == "V-02" for c in state["_va_result"]["failed_checks"])
        assert state["artifacts"]["feature_definition"]["goal"] == "Pay with wallet"


def test_va_discuss_llm_does_not_mutate_artifacts_or_status(monkeypatch):
    from agents.sub_graph.validation_agent.logic import run_va_turn

    monkeypatch.setattr(
        "agents.sub_graph.validation_agent.llm.maybe_llm_completion",
        lambda *_a, **_k: (
            "Finding V-02: BR-01 is missing from workflow. "
            "Wiki PAGE-FINANCE-ORG. Open BA chat to edit BR — I will not change artifacts."
        ),
    )
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        state = {
            "feature_status": "VALIDATED",
            "package_exported": False,
            "last_validation": {
                "status": "passed",
                "agent_response": "📋 **Validation PASSED**",
                "failed_checks": [],
                "warnings": [],
                "evidence_references": [
                    {"page_id": "PAGE-FINANCE-ORG", "title": "Finance"}
                ],
            },
            "flags": _tier1_pass_flags(),
            "sections_status": {"feature_definition": "completed"},
            "artifacts": {"feature_definition": {"goal": "keep-llm"}},
        }
        msg = run_va_turn(state, store, "why did wiki show up?")
        assert "PAGE-FINANCE-ORG" in msg or "V-02" in msg
        assert state["artifacts"]["feature_definition"]["goal"] == "keep-llm"
        assert state["feature_status"] == "VALIDATED"
        assert state["last_validation"]["status"] == "passed"
        assert state["flags"]["fd"]["FD-F1"]["status"] == "PASS"


def test_route_va_turn_validate_vs_discuss():
    from agents.sub_graph.validation_agent.agent import (
        ROUTE_VA_DISCUSS,
        ROUTE_VA_RUN,
        route_va_turn,
    )

    validate_ctx = _ctx({"_va_run_validate": True}, "[VALIDATE] go")
    route_va_turn(validate_ctx)
    assert validate_ctx.route == ROUTE_VA_RUN

    discuss_ctx = _ctx({}, "what failed on V-02?")
    route_va_turn(discuss_ctx)
    assert discuss_ctx.route == ROUTE_VA_DISCUSS


def test_firm_wiki_vw01_blocks_export_and_cites_page():
    from agents.sub_graph.validation_agent.checks import RULESET_VERSION
    from agents.sub_graph.validation_agent.logic import run_validation
    from managers.control.status import can_export

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        store.seed_page(
            page_id="L-PG-THRESHOLD",
            title="Ngưỡng 10 triệu",
            body="Giao dịch trên 10 triệu VND phải có phê duyệt cấp PO. Discount 15%.",
            project_id="PRJ-MES-01",
            bucket_id="business_rule",
        )
        state = {
            "session_id": "sid-wiki-firm",
            "project_id": "PRJ-MES-01",
            "feature_title": "Theo dõi giao dịch",
            "artifacts": {
                "feature_definition": {
                    "goal": "Theo dõi giao dịch chi tiêu",
                    "actors": ["ACT-PO: Product Owner"],
                    "scope_in": ["ghi nhận giao dịch"],
                    "scope_out": ["thanh toán quốc tế"],
                },
                "business_rules": [
                    {
                        "id": "BR-01",
                        "statement": "Giao dịch phải được ghi nhận trên hệ thống",
                    }
                ],
                "workflow": {
                    "workflow_md_content": "## Main Flow\n1. ACT-PO ghi nhận BR-01\n"
                },
                "use_cases": [
                    {
                        "id": "US-01",
                        "actor_id": "ACT-PO",
                        "statement": "Là PO, tôi muốn ghi nhận giao dịch để kiểm soát",
                        "rule_ids": ["BR-01"],
                        "acceptance_criteria": [
                            {
                                "given": "có giao dịch",
                                "when": "ghi nhận",
                                "then": "được lưu",
                            }
                        ],
                    }
                ],
            },
        }
        run_validation(state, store)
        result = state["_va_result"]
        assert result["status"] == "failed"
        assert result["ruleset_version"] == RULESET_VERSION == "ba-va-1.1.0"
        wiki_fails = [
            c for c in result["failed_checks"] if str(c.get("check_id", "")).startswith("V-WIKI")
        ]
        assert any(c.get("check_id") == "V-WIKI-01" for c in wiki_fails)
        assert any(c.get("evidence_page_id") == "L-PG-THRESHOLD" for c in wiki_fails)
        assert can_export("VALIDATION_FAILED", result) is False


def test_firm_wiki_vw02_story_contradiction():
    from agents.sub_graph.validation_agent.logic import run_validation

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        store.seed_page(
            page_id="L-PG-CUTOFF",
            title="Checkout cutoff",
            body=(
                "Sau cutoff 22:00, checkout bị chặn. "
                "Khách không được checkout sau giờ cutoff."
            ),
            project_id="PRJ-MES-01",
        )
        state = {
            "session_id": "sid-vw02",
            "project_id": "PRJ-MES-01",
            "artifacts": {
                "feature_definition": {
                    "goal": "Checkout đơn hàng sau cutoff",
                    "actors": ["ACT-KHACH: Khách"],
                    "scope_in": ["checkout"],
                    "scope_out": [],
                },
                "business_rules": [
                    {
                        "id": "BR-01",
                        "statement": "Sau cutoff vẫn cho phép checkout kèm disclaimer",
                    }
                ],
                "workflow": {
                    "workflow_md_content": "## Main Flow\n1. ACT-KHACH checkout BR-01\n"
                },
                "use_cases": [
                    {
                        "id": "US-01",
                        "actor_id": "ACT-KHACH",
                        "statement": (
                            "Là khách, tôi muốn checkout sau cutoff để hoàn tất đơn"
                        ),
                        "rule_ids": ["BR-01"],
                        "acceptance_criteria": [
                            {
                                "given": "đã qua cutoff",
                                "when": "khách checkout",
                                "then": "hệ thống cho phép checkout với disclaimer",
                            }
                        ],
                    }
                ],
            },
        }
        run_validation(state, store)
        assert state["_va_result"]["status"] == "failed"
        assert any(
            c.get("check_id") == "V-WIKI-02"
            and c.get("evidence_page_id") == "L-PG-CUTOFF"
            for c in state["_va_result"]["failed_checks"]
        )


def test_firm_wiki_vw03_two_pages_contradict():
    from agents.sub_graph.validation_agent.logic import run_validation

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        store.seed_page(
            page_id="L-PG-OLD",
            title="Approval threshold old",
            body="Giao dịch trên 5 triệu VND phải có phê duyệt.",
            project_id="PRJ-MES-01",
        )
        store.seed_page(
            page_id="L-PG-NEW",
            title="Approval threshold new",
            body="Giao dịch trên 20 triệu VND phải có phê duyệt.",
            project_id="PRJ-MES-01",
        )
        state = {
            "session_id": "sid-vw03",
            "project_id": "PRJ-MES-01",
            "artifacts": {
                "feature_definition": {
                    "goal": "Phê duyệt giao dịch nội bộ",
                    "actors": ["ACT-PO: PO"],
                    "scope_in": ["phê duyệt"],
                    "scope_out": [],
                },
                "business_rules": [
                    {
                        "id": "BR-01",
                        "statement": "Giao dịch trên 5 triệu VND phải có phê duyệt",
                    }
                ],
                "workflow": {
                    "workflow_md_content": "## Main Flow\n1. ACT-PO phê duyệt BR-01\n"
                },
                "use_cases": [],
            },
        }
        run_validation(state, store)
        assert state["_va_result"]["status"] == "failed"
        assert any(
            c.get("check_id") == "V-WIKI-03" for c in state["_va_result"]["failed_checks"]
        )


def test_firm_wiki_matching_package_passes_wiki_errors():
    from agents.sub_graph.validation_agent.logic import run_validation

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        store.seed_page(
            page_id="L-PG-OK",
            title="Ghi nhận giao dịch",
            body=(
                "Giao dịch phải được ghi nhận trên hệ thống. "
                "ACT-PO thực hiện ghi nhận theo BR-01."
            ),
            project_id="PRJ-MES-01",
        )
        state = {
            "session_id": "sid-wiki-ok",
            "project_id": "PRJ-MES-01",
            "artifacts": {
                "feature_definition": {
                    "goal": "Theo dõi giao dịch chi tiêu nội bộ",
                    "actors": ["ACT-PO: Product Owner"],
                    "scope_in": ["ghi nhận giao dịch"],
                    "scope_out": ["thanh toán quốc tế"],
                },
                "business_rules": [
                    {
                        "id": "BR-01",
                        "statement": "Giao dịch phải được ghi nhận trên hệ thống",
                    }
                ],
                "workflow": {
                    "workflow_md_content": (
                        "## Main Flow\n1. ACT-PO ghi nhận giao dịch BR-01\n"
                        "## Exception Flows\nE-01 timeout\n"
                    )
                },
                "use_cases": [
                    {
                        "id": "US-01",
                        "actor_id": "ACT-PO",
                        "statement": (
                            "Là PO, tôi muốn ghi nhận giao dịch để kiểm soát chi tiêu"
                        ),
                        "rule_ids": ["BR-01"],
                        "acceptance_criteria": [
                            {
                                "given": "có giao dịch",
                                "when": "ghi nhận",
                                "then": "giao dịch được ghi nhận trên hệ thống",
                            }
                        ],
                    }
                ],
            },
        }
        run_validation(state, store)
        result = state["_va_result"]
        wiki_errors = [
            c
            for c in result["failed_checks"]
            if str(c.get("check_id", "")).startswith("V-WIKI-0")
            and c.get("check_id") != "V-WIKI-05"
        ]
        assert wiki_errors == []
        assert result["status"] in {"passed", "passed_with_warnings"}


def test_firm_wiki_vw04_scope_out_and_vw05_warning():
    from agents.sub_graph.validation_agent.logic import run_validation
    from agents.sub_graph.validation_agent.wiki_checks import run_firm_wiki_checks

    pages = [
        {
            "page_id": "L-PG-SCOPE",
            "title": "International pay",
            "body": (
                "Hệ thống hỗ trợ thanh toán quốc tế trong phạm vi. "
                "ACT-SUPPLIER phải thực hiện bước thanh toán."
            ),
        }
    ]
    artifacts = {
        "feature_definition": {
            "goal": "Checkout nội địa",
            "actors": ["ACT-KHACH: Khách"],
            "scope_in": ["checkout nội địa"],
            "scope_out": ["thanh toán quốc tế"],
        },
        "business_rules": [
            {"id": "BR-99", "statement": "Phải kiểm tra hạn mức tín dụng trước khi ship"}
        ],
        "use_cases": [
            {
                "id": "US-09",
                "actor_id": "ACT-KHACH",
                "statement": "Là khách, tôi muốn xem hạn mức tín dụng để quyết định mua",
                "acceptance_criteria": [],
            }
        ],
    }
    failed, warnings = run_firm_wiki_checks(pages=pages, artifacts=artifacts)
    assert any(c.get("check_id") == "V-WIKI-04" for c in failed)
    assert any(c.get("check_id") == "V-WIKI-05" for c in warnings)

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        store.seed_page(
            page_id="L-PG-SCOPE",
            title="International pay",
            body=pages[0]["body"],
            project_id="PRJ-MES-01",
        )
        state = {
            "session_id": "sid-vw04",
            "project_id": "PRJ-MES-01",
            "artifacts": {
                **artifacts,
                "workflow": {"workflow_md_content": "## Main Flow\n1. ACT-KHACH checkout\n"},
            },
        }
        run_validation(state, store)
        assert state["_va_result"]["status"] == "failed"
        assert any(
            c.get("check_id") == "V-WIKI-04" for c in state["_va_result"]["failed_checks"]
        )


def test_wiki_context_ack_hides_drafts():
    from agents.sub_graph.shared.wiki_context import (
        collect_approved_wiki_hits,
        format_approved_wiki_context,
    )

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        store.seed_page(
            page_id="PAGE-OK",
            title="Approved policy",
            body="Approved body about checkout.",
            project_id="PRJ-MES-01",
            status="approved",
        )
        store.seed_page(
            page_id="PAGE-DRAFT",
            title="Draft secret",
            body="Must stay hidden.",
            project_id="PRJ-MES-01",
            status="draft",
        )
        state = {
            "project_id": "PRJ-MES-01",
            "feature_title": "checkout",
            "artifacts": {
                "feature_definition": {
                    "goal": "checkout flow",
                    "scope_in": ["checkout"],
                }
            },
        }
        hits = collect_approved_wiki_hits(state, store=store)
        assert any(h["page_id"] == "PAGE-OK" for h in hits)
        assert all(h["page_id"] != "PAGE-DRAFT" for h in hits)
        text = format_approved_wiki_context(state, store=store)
        assert "PAGE-OK" in text
        assert "PAGE-DRAFT" not in text
        assert "already agreed" in text.lower() or "APPROVED WIKI" in text

