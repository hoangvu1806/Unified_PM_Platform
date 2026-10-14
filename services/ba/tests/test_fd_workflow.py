"""Unit & Integration tests for Feature Definition Workflow Subgraph."""

import pytest
from unittest.mock import MagicMock
from google.adk import Context

from agents.sub_graph.feature_definition.schemas import (
    FeatureDefinitionData,
    OQASMDetectionData,
    OpenQuestionItem,
    AssumptionItem,
)
from agents.sub_graph.feature_definition.nodes.extractor.callback import fd_merge_callback
from agents.sub_graph.feature_definition.nodes.oq_asm_detector.callback import (
    apply_oq_resolutions,
    oq_asm_merge_callback,
    resolutions_from_user_message,
)
from agents.sub_graph.feature_definition.nodes import check_fd_flags_logic


@pytest.mark.anyio
async def test_fd_merge_callback():
    """Test merging delta FD Extractor output into context state."""
    mock_context = MagicMock()
    mock_context.state = {}

    mock_response = MagicMock()
    mock_response.content.parts[0].text = """{
        "goal": "Giảm tỷ lệ bỏ giỏ hàng 30%",
        "actors": ["ACT-CUSTOMER: Khách hàng", "ACT-PAYMENT-GW: Gateway"],
        "scope_in": ["Thanh toán MoMo"],
        "scope_out": ["Thẻ tín dụng"]
    }"""

    await fd_merge_callback(mock_context, mock_response)

    artifact = mock_context.state["artifacts"]["feature_definition"]
    assert artifact["goal"] == "Giảm tỷ lệ bỏ giỏ hàng 30%"
    assert len(artifact["actors"]) == 2
    assert artifact["scope_in"] == ["Thanh toán MoMo"]
    assert artifact["scope_out"] == ["Thẻ tín dụng"]


@pytest.mark.anyio
async def test_oq_asm_merge_callback():
    """Test merging detected OQ and Assumptions into context state."""
    mock_context = MagicMock()
    mock_context.state = {"current_turn": 1, "active_section": "feature_definition"}

    mock_response = MagicMock()
    mock_response.content.parts[0].text = """{
        "open_questions": [
            {
                "question": "Hạn mức nạp tối đa là bao nhiêu?",
                "severity": "critical",
                "assigned_to": "PO",
                "impact": "Ảnh hưởng chính sách thanh toán"
            }
        ],
        "assumptions": [
            {
                "statement": "Hệ thống đã có sẵn API Gateway"
            }
        ]
    }"""

    await oq_asm_merge_callback(mock_context, mock_response)

    oqs = mock_context.state["open_questions"]
    asms = mock_context.state["assumptions"]

    assert len(oqs) == 1
    assert oqs[0]["id"] == "OQ-001"
    assert oqs[0]["question"] == "Hạn mức nạp tối đa là bao nhiêu?"
    assert oqs[0]["severity"] == "critical"

    assert len(asms) == 1
    assert asms[0]["id"] == "ASM-01"
    assert asms[0]["statement"] == "Hệ thống đã có sẵn API Gateway"

    # Test deduplication on second call with duplicate item + 1 new item
    mock_response_dup = MagicMock()
    mock_response_dup.content.parts[0].text = """{
        "open_questions": [
            {
                "question": "Hạn mức nạp tối đa là bao nhiêu?",
                "severity": "critical",
                "assigned_to": "PO",
                "impact": "Ảnh hưởng chính sách thanh toán"
            },
            {
                "question": "Thời gian timeout của GD là bao lâu?",
                "severity": "warning",
                "assigned_to": "Tech Lead",
                "impact": "Ảnh hưởng trải nghiệm user"
            }
        ],
        "assumptions": [
            {
                "statement": "Hệ thống đã có sẵn API Gateway"
            }
        ]
    }"""

    await oq_asm_merge_callback(mock_context, mock_response_dup)

    assert len(mock_context.state["open_questions"]) == 2
    assert mock_context.state["open_questions"][1]["id"] == "OQ-002"
    assert (
        mock_context.state["open_questions"][1]["question"]
        == "Thời gian timeout của GD là bao lâu?"
    )
    assert len(mock_context.state["assumptions"]) == 1


def test_oq_resolution_from_user_message_and_llm():
    state = {
        "open_questions": [
            {
                "id": "OQ-001",
                "question": "Ngưỡng phê duyệt là bao nhiêu?",
                "severity": "critical",
                "status": "open",
                "answer": None,
            }
        ]
    }
    assert resolutions_from_user_message("OQ-001: 50 triệu VND, PO duyệt") == [
        {"id": "OQ-001", "answer": "50 triệu VND, PO duyệt", "status": "resolved"}
    ]
    n = apply_oq_resolutions(
        state,
        [{"id": "OQ-001", "answer": "50 triệu VND, PO duyệt", "status": "resolved"}],
    )
    assert n == 1
    assert state["open_questions"][0]["status"] == "resolved"
    assert state["open_questions"][0]["answer"] == "50 triệu VND, PO duyệt"
    assert apply_oq_resolutions(state, [{"id": "OQ-999", "answer": "nope"}]) == 0


@pytest.mark.anyio
async def test_oq_asm_merge_resolves_existing_critical():
    mock_context = MagicMock()
    mock_context.state = {
        "current_turn": 2,
        "active_section": "feature_definition",
        "open_questions": [
            {
                "id": "OQ-001",
                "question": "Ngưỡng phê duyệt là bao nhiêu?",
                "severity": "critical",
                "status": "open",
                "answer": None,
            }
        ],
        "assumptions": [],
    }
    mock_context.user_content.parts = [
        MagicMock(text="Trả lời OQ-001: ngưỡng 50 triệu VND, PO phê duyệt.")
    ]
    mock_response = MagicMock()
    mock_response.content.parts[0].text = """{
        "open_questions": [],
        "assumptions": [],
        "resolved_questions": [
            {"id": "OQ-001", "answer": "50 triệu VND, PO phê duyệt", "status": "resolved"}
        ]
    }"""
    await oq_asm_merge_callback(mock_context, mock_response)
    oq = mock_context.state["open_questions"][0]
    assert oq["status"] == "resolved"
    assert "50 triệu" in oq["answer"]


def test_fd_flags_checker_node():
    """Test FunctionNode checking completion flags based on state data."""
    ctx = MagicMock(spec=Context)
    ctx.state = {
        "artifacts": {
            "feature_definition": {
                "goal": "Giảm tỷ lệ bỏ giỏ 30%",
                "actors": ["ACT-CUSTOMER: Customer", "ACT-GW: Gateway"],
                "scope_in": ["Thanh toán MoMo"],
                "scope_out": ["Ví nội bộ"],
            }
        }
    }

    flags = check_fd_flags_logic(ctx)

    assert flags["FD-F1"]["status"] == "PENDING_SEMANTIC"
    assert flags["FD-F2"]["status"] == "PASS"
    assert flags["FD-F3"]["status"] == "PASS"
    assert flags["FD-F4"]["status"] == "PASS"
    assert flags["FD-F5"]["status"] == "PENDING_SEMANTIC"


def test_fd_flags_checker_missing_value():
    """Test flags_checker sets MISSING_VALUE for empty required data."""
    ctx = MagicMock(spec=Context)
    ctx.state = {
        "artifacts": {
            "feature_definition": {
                "goal": "",
                "actors": [],
                "scope_in": [],
                "scope_out": [],
            }
        }
    }

    flags = check_fd_flags_logic(ctx)

    assert flags["FD-F1"]["status"] == "MISSING_VALUE"
    assert flags["FD-F2"]["status"] == "MISSING_VALUE"
    assert flags["FD-F3"]["status"] == "MISSING_VALUE"


def test_fd_flags_checker_fail_insufficient_quantity():
    """Test flags_checker sets FAIL when data exists but quantity is insufficient."""
    ctx = MagicMock(spec=Context)
    ctx.state = {
        "artifacts": {
            "feature_definition": {
                "goal": "Quản lý đơn hàng",
                "actors": ["Khách hàng"],
                "scope_in": ["Tạo đơn"],
                "scope_out": [],
            }
        }
    }

    flags = check_fd_flags_logic(ctx)

    assert flags["FD-F2"]["status"] == "FAIL"
    assert "hiện có 1" in flags["FD-F2"]["detail"]


def test_fd_flags_checker_preserves_pass():
    """Test check_fd_flags_logic preserves prior PASS semantic evaluations."""
    ctx = MagicMock(spec=Context)
    ctx.state = {
        "artifacts": {
            "feature_definition": {
                "goal": "Giảm tỷ lệ bỏ giỏ 30%",
                "actors": ["ACT-CUSTOMER: Customer", "ACT-GW: Gateway"],
                "scope_in": ["Thanh toán MoMo"],
                "scope_out": ["Ví nội bộ"],
            }
        },
        "flags": {
            "fd": {
                "FD-F1": {"status": "PASS", "detail": None},
                "FD-F5": {"status": "PASS", "detail": None},
            }
        },
    }

    flags = check_fd_flags_logic(ctx)

    assert flags["FD-F1"]["status"] == "PASS"
    assert flags["FD-F5"]["status"] == "PASS"


def test_fd_flags_checker_resets_not_yet_reasonable():
    """Test flags_checker resets NOT_YET_REASONABLE to PENDING_SEMANTIC for re-evaluation."""
    ctx = MagicMock(spec=Context)
    ctx.state = {
        "artifacts": {
            "feature_definition": {
                "goal": "Cải thiện trải nghiệm thanh toán",
                "actors": ["Khách hàng", "MoMo Gateway"],
                "scope_in": ["Thanh toán MoMo"],
                "scope_out": ["Thẻ tín dụng"],
            }
        },
        "flags": {
            "fd": {
                "FD-F1": {"status": "NOT_YET_REASONABLE", "detail": "Goal chưa nêu rõ giá trị"},
                "FD-F5": {"status": "NOT_YET_REASONABLE", "detail": "Chưa xác nhận"},
            }
        },
    }

    flags = check_fd_flags_logic(ctx)

    assert flags["FD-F1"]["status"] == "PENDING_SEMANTIC"
    assert flags["FD-F5"]["status"] == "PENDING_SEMANTIC"


def test_update_feature_flag_status_pass():
    """Test tool correctly sets PASS and reports section completion."""
    from google.adk.tools import ToolContext
    from agents.sub_graph.feature_definition.nodes.flags_checker.tools import update_feature_flag_status

    mock_ctx = MagicMock(spec=ToolContext)
    mock_ctx.state = {
        "flags": {
            "fd": {
                "FD-F1": {"status": "PENDING_SEMANTIC"},
                "FD-F2": {"status": "PASS"},
                "FD-F3": {"status": "PASS"},
                "FD-F4": {"status": "PASS"},
                "FD-F5": {"status": "PASS"},
            }
        }
    }

    res = update_feature_flag_status(mock_ctx, flag_id="FD-F1", status="PASS")
    assert "[THÀNH CÔNG]" in res
    assert "HOÀN THÀNH" in res
    assert mock_ctx.state["flags"]["fd"]["FD-F1"]["status"] == "PASS"
    assert mock_ctx.state["sections_status"]["feature_definition"] == "completed"


def test_update_feature_flag_status_not_yet_reasonable():
    """Test tool correctly sets NOT_YET_REASONABLE with detail."""
    from google.adk.tools import ToolContext
    from agents.sub_graph.feature_definition.nodes.flags_checker.tools import update_feature_flag_status

    mock_ctx = MagicMock(spec=ToolContext)
    mock_ctx.state = {
        "flags": {
            "fd": {
                "FD-F1": {"status": "PENDING_SEMANTIC"},
                "FD-F2": {"status": "PASS"},
                "FD-F3": {"status": "PASS"},
                "FD-F4": {"status": "PASS"},
                "FD-F5": {"status": "PASS"},
            }
        }
    }

    res = update_feature_flag_status(
        mock_ctx, flag_id="FD-F1", status="NOT_YET_REASONABLE",
        detail="Goal chỉ là tên gọi, chưa nêu giá trị"
    )
    assert "[CHƯA HỢP LÝ]" in res
    assert "Goal chỉ là tên gọi" in res
    assert mock_ctx.state["flags"]["fd"]["FD-F1"]["status"] == "NOT_YET_REASONABLE"
    assert mock_ctx.state["sections_status"]["feature_definition"] == "in_progress"


def test_update_feature_flag_status_invalid():
    """Test tool rejects invalid status values."""
    from google.adk.tools import ToolContext
    from agents.sub_graph.feature_definition.nodes.flags_checker.tools import update_feature_flag_status

    mock_ctx = MagicMock(spec=ToolContext)
    mock_ctx.state = {"flags": {"fd": {}}}

    res = update_feature_flag_status(mock_ctx, flag_id="FD-F1", status="INVALID")
    assert "Lỗi" in res


@pytest.mark.anyio
async def test_fd_discussion_inject_callback():
    """Test fd_discussion_inject_callback injects 4 context blocks (Artifacts, Missing Values, OQs, ASMs)."""
    from agents.sub_graph.feature_definition.nodes.discussion.callback import fd_discussion_inject_callback

    mock_context = MagicMock()
    mock_context.session.events = []
    mock_context.state = {
        "artifacts": {
            "feature_definition": {
                "goal": "Quản lý đơn hàng tự động",
                "actors": ["Khách hàng"],
            }
        },
        "flags": {
            "fd": {
                "FD-F1": {"status": "FAIL", "detail": "Chưa rõ goal"},
            }
        },
        "open_questions": [
            {"id": "OQ-001", "question": "Hỗ trợ ví nào?", "status": "open"}
        ],
        "assumptions": [
            {"id": "ASM-01", "statement": "User đã đăng nhập"}
        ],
    }

    mock_llm_request = MagicMock()
    mock_llm_request.contents = []

    await fd_discussion_inject_callback(mock_context, mock_llm_request)

    # Check injected text
    system_parts = [p.text for c in mock_llm_request.contents for p in c.parts if hasattr(p, "text")]
    injected_text = "\n".join(system_parts)

    assert "=== CURRENT ARTIFACT DATA ===" in injected_text
    assert "=== CHECKLIST ===" in injected_text
    assert "=== OPEN QUESTIONS ===" in injected_text
    assert "=== ASSUMPTIONS ===" in injected_text
    assert "OQ-001" in injected_text
    assert "ASM-01" in injected_text

