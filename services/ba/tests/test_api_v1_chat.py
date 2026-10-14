"""Unit tests for API V1 Chat endpoints and Pydantic schemas."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server import app
from managers.service import (
    AgentChatRequest,
    AgentChatResponse,
    ExtraDataInfo,
    SectionStatusInfo,
    TicketType,
)


def test_agent_chat_request_schema_valid():
    """Test valid AgentChatRequest schema construction."""
    req = AgentChatRequest(
        user_id="user-123",
        ticket_type=TicketType.NEW_FEATURE,
        user_message="Hello agent",
    )
    assert req.user_id == "user-123"
    assert req.ticket_type == TicketType.NEW_FEATURE
    assert req.user_message == "Hello agent"


def test_agent_chat_request_schema_invalid_enum():
    """Test AgentChatRequest validation with invalid ticket_type enum."""
    with pytest.raises(ValidationError):
        AgentChatRequest(
            user_id="user-123",
            ticket_type="INVALID_TICKET_TYPE",
            user_message="Hello",
        )


def test_agent_chat_response_schema():
    """Test AgentChatResponse schema construction with extra_data buttons list[str]."""
    resp = AgentChatResponse(
        session_id="test-session-123",
        user_id="user-123",
        ticket_type=TicketType.NEW_FEATURE,
        agent_response="Ghi nhận thành công.",
        section_status=SectionStatusInfo(
            current_section="feature_definition",
            can_proceed_to_validation=False,
        ),
        extra_data=ExtraDataInfo(
            images=[],
            buttons=["Chuyển sang Business Rules", "Validate ngay"],
        ),
    )
    assert resp.session_id == "test-session-123"
    assert resp.agent_response == "Ghi nhận thành công."
    assert resp.extra_data.buttons == ["Chuyển sang Business Rules", "Validate ngay"]


def test_v1_chat_message_sync_endpoint_uninitialized():
    """Test /api/v1/chat/{session_id}/message returns 503 when ADK runner is not initialized."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/test-session-id/message",
        json={
            "user_id": "ba-user-01",
            "ticket_type": "NEW_FEATURE",
            "user_message": "Test message",
        },
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "ADK Runner not initialized"}


def test_v1_chat_message_stream_endpoint_uninitialized():
    """Test /api/v1/chat/{session_id}/stream returns 503 when ADK runner is not initialized."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/test-session-id/stream",
        json={
            "user_id": "ba-user-01",
            "ticket_type": "NEW_FEATURE",
            "user_message": "Test message",
        },
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "ADK Runner not initialized"}


def test_v1_chat_input_validation():
    """Test validation checks for empty/whitespace inputs."""
    from managers.service.api import _validate_chat_input

    req_empty_msg = AgentChatRequest(
        user_id="user-1", ticket_type=TicketType.NEW_FEATURE, user_message="   "
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_chat_input("valid-session", req_empty_msg)
    assert exc_info.value.status_code == 400
    assert "user_message không được để trống" in exc_info.value.detail

    req_valid = AgentChatRequest(
        user_id="user-1", ticket_type=TicketType.NEW_FEATURE, user_message="Hello"
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_chat_input("  ", req_valid)
    assert exc_info.value.status_code == 400
    assert "session_id không được để trống" in exc_info.value.detail


@pytest.mark.anyio
async def test_partial_state_is_persisted_after_a_failed_turn():
    """Completed node output must survive a later timeout/error."""
    from managers.service.api import _persist_latest_state

    state = {"artifacts": {"business_rules": [{"id": "BR-01"}]}}
    session_service = SimpleNamespace(
        get_session=AsyncMock(return_value=SimpleNamespace(state=state))
    )
    with patch("managers.service.api.persist_session_artifacts") as persist:
        result = await _persist_latest_state(session_service, "ba-user", "session-1")

    persist.assert_called_once_with(state, "session-1")
    assert result == state

