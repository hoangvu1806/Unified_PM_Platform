"""Integration and unit tests for Multi-Runner registry, V1 Chat API endpoints, and Feature CRUD APIs."""

from unittest.mock import PropertyMock, patch

import anyio
import pytest
from fastapi.testclient import TestClient
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from config.base_config import Settings
import managers.runner_context as rc
from server import app


@pytest.fixture(autouse=True)
def setup_adk_runner():
    """Fixture to initialize ADK runners in memory for testing."""
    test_db_url = "sqlite+aiosqlite:///:memory:"
    with patch.object(Settings, "database_url", new_callable=PropertyMock, return_value=test_db_url):
        anyio.run(rc.init_adk)
    yield
    rc._runner = None
    rc._session_service = None


# ── 1. Multi-Runner Accessor Tests ─────────────────────────────


def test_get_runner_all_ticket_types():
    """Verify get_runner returns the unified runner for each supported ticket type."""
    for ticket in ["NEW_FEATURE", "FEATURE_ENHANCEMENT", "BUG_FIX_LOG", "PROCESS_OPTIMIZATION"]:
        runner = rc.get_runner(ticket)
        assert runner is not None
        assert runner.app_name == "ba-agent"


def test_get_runner_unsupported_ticket_type():
    """Verify get_runner raises HTTP 400 for unsupported ticket type."""
    with pytest.raises(rc.HTTPException) as exc:
        rc.get_runner("UNKNOWN_TICKET_TYPE")
    assert exc.value.status_code == 400
    assert "chưa được hỗ trợ" in exc.value.detail


def test_get_runner_uninitialized():
    """Verify get_runner raises HTTP 503 when the unified runner is missing."""
    saved_runner = rc._runner
    try:
        rc._runner = None
        with pytest.raises(rc.HTTPException) as exc:
            rc.get_runner("NEW_FEATURE")
        assert exc.value.status_code == 503
        assert exc.value.detail == rc.RUNNER_NOT_INITIALIZED
    finally:
        rc._runner = saved_runner


# ── 2. End-to-End API V1 Chat Sync Message Tests ───────────────


@pytest.mark.anyio
async def test_v1_chat_message_sync_new_feature():
    """Test /api/v1/chat/{session_id}/message with NEW_FEATURE ticket type."""
    client = TestClient(app)

    mock_json_response = (
        '{"goal": "Thanh toán QR", "actors": ["ACT-CUSTOMER: Khách hàng"], '
        '"scope_in": ["Quét mã QR"], "scope_out": [], '
        '"open_questions": [], "assumptions": []}'
    )

    mock_llm_res = LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=mock_json_response)],
        ),
        turn_complete=True,
    )

    async def dummy_lite_llm_gen(*args, **kwargs):
        yield mock_llm_res

    with patch("google.adk.models.lite_llm.LiteLlm.generate_content_async", side_effect=dummy_lite_llm_gen):
        response = client.post(
            "/api/v1/chat/sync-session-01/message",
            json={
                "user_id": "user-test",
                "ticket_type": "NEW_FEATURE",
                "user_message": "Tôi muốn tạo tính năng QR Code",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "sync-session-01"
    assert data["ticket_type"] == "NEW_FEATURE"
    assert "section_status" in data
    assert data["section_status"]["current_section"] == "feature_definition"


@pytest.mark.anyio
async def test_v1_chat_message_sync_placeholder_agent():
    """Test /api/v1/chat/{session_id}/message with BUG_FIX_LOG placeholder agent."""
    client = TestClient(app)

    mock_llm_res = LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text="Ghi nhận báo lỗi từ người dùng.")],
        ),
        turn_complete=True,
    )

    async def dummy_lite_llm_gen(*args, **kwargs):
        yield mock_llm_res

    with patch("google.adk.models.lite_llm.LiteLlm.generate_content_async", side_effect=dummy_lite_llm_gen):
        response = client.post(
            "/api/v1/chat/bug-session-01/message",
            json={
                "user_id": "user-test",
                "ticket_type": "BUG_FIX_LOG",
                "user_message": "Ứng dụng bị văng khi bấm nút gửi",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "bug-session-01"
    assert data["ticket_type"] == "BUG_FIX_LOG"


# ── 3. End-to-End API V1 Chat Stream SSE Tests ──────────────────


@pytest.mark.anyio
async def test_v1_chat_message_stream_sse():
    """Test /api/v1/chat/{session_id}/stream returns Server-Sent Events."""
    client = TestClient(app)

    mock_json_response = (
        '{"goal": "Thanh toán QR", "actors": ["ACT-CUSTOMER: Khách hàng"], '
        '"scope_in": ["Quét mã QR"], "scope_out": [], '
        '"open_questions": [], "assumptions": []}'
    )

    mock_llm_res = LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=mock_json_response)],
        ),
        turn_complete=True,
    )

    async def dummy_lite_llm_gen(*args, **kwargs):
        yield mock_llm_res

    with patch("google.adk.models.lite_llm.LiteLlm.generate_content_async", side_effect=dummy_lite_llm_gen):
        response = client.post(
            "/api/v1/chat/stream-session-01/stream",
            json={
                "user_id": "user-test",
                "ticket_type": "NEW_FEATURE",
                "user_message": "Chào bạn",
            },
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    content_text = response.text
    assert "event: chat.message" in content_text or "event: chat.done" in content_text


# ── 4. Feature CRUD Endpoints Tests ─────────────────────────────


@pytest.fixture
def sqlite_sync_db():
    """In-process SQLite for Feature CRUD — no live Postgres required."""
    from managers.database.connection import (
        configure_sync_engine,
        get_sync_database_url,
        init_db,
    )

    configure_sync_engine("sqlite:///:memory:")
    init_db()
    yield
    configure_sync_engine(get_sync_database_url())


def test_production_sync_url_remains_postgres():
    """Production default must stay Postgres even when tests rebind the engine."""
    from managers.database.connection import get_sync_database_url

    assert get_sync_database_url().startswith("postgresql+psycopg2://")


def test_feature_crud_lifecycle(sqlite_sync_db):
    """Test full Feature CRUD lifecycle (/api/features/)."""
    client = TestClient(app)

    # 1. Create Feature
    create_resp = client.post(
        "/api/features/",
        json={
            "title": "Tính năng Đăng ký tài khoản",
            "description": "Cho phép người dùng mới tạo tài khoản qua OTP SMS",
        },
    )
    assert create_resp.status_code == 201
    feature_data = create_resp.json()
    session_id = feature_data["session_id"]
    assert feature_data["title"] == "Tính năng Đăng ký tài khoản"
    assert feature_data["sections_total"] == 4

    # 2. List Features
    list_resp = client.get("/api/features/")
    assert list_resp.status_code == 200
    features_list = list_resp.json()
    assert any(item["session_id"] == session_id for item in features_list)

    # 3. Get Feature Details
    get_resp = client.get(f"/api/features/{session_id}")
    assert get_resp.status_code == 200
    details = get_resp.json()
    assert details["session_id"] == session_id
    assert details["title"] == "Tính năng Đăng ký tài khoản"

    # 4. Get Chat History
    history_resp = client.get(f"/api/features/{session_id}/history")
    assert history_resp.status_code == 200
    history_data = history_resp.json()
    assert history_data["session_id"] == session_id
    assert "messages" in history_data

    # 5. Delete Feature
    delete_resp = client.delete(f"/api/features/{session_id}")
    assert delete_resp.status_code == 204

    # 6. Verify NotFound after deletion
    get_after_delete = client.get(f"/api/features/{session_id}")
    assert get_after_delete.status_code == 404
