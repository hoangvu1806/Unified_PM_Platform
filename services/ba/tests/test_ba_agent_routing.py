"""Integration test for top-level BA Agent routing to Feature Definition Subgraph."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dotenv import load_dotenv

load_dotenv()

from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.ba_agent.new_feature_agent import create_new_feature_agent


@pytest.mark.anyio
async def test_ba_agent_routes_to_fd_and_responds(monkeypatch):
    """Test sending a message to top-level `ba_agent` routes to `fd_subgraph` and returns discussion response."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_key_for_test")
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="ba_agent_test",
        agent=create_new_feature_agent(),
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="ba_agent_test",
        user_id="test_user",
    )

    user_message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text="Tôi muốn thêm tính năng thanh toán qua ví MoMo và ZaloPay. Hạn mức nạp chưa rõ để hỏi lại PO."
            )
        ],
    )

    # Mock LLM generate_content_async response
    mock_llm_response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part.from_text(
                    text='{"goal": "Thanh toán MoMo/ZaloPay", "actors": ["ACT-CUSTOMER: Khách hàng", "ACT-GW: Gateway"], "scope_in": ["Thanh toán MoMo"], "scope_out": []}'
                )
            ],
        ),
        finish_reason=types.FinishReason.STOP,
    )

    mock_llm_res = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part.from_text(
                    text='{"goal": "Thanh toán MoMo", "actors": ["ACT-CUSTOMER: Customer", "ACT-GW: Gateway"], "scope_in": ["Thanh toán MoMo"], "scope_out": []}'
                )
            ],
        ),
        turn_complete=True,
    )

    async def dummy_lite_llm_gen(*args, **kwargs):
        yield mock_llm_res

    with patch("google.genai.models.AsyncModels.generate_content", new_callable=AsyncMock) as mock_gen, \
         patch("google.adk.models.lite_llm.LiteLlm.generate_content_async", side_effect=dummy_lite_llm_gen), \
         patch("google.adk.models.llm_response.LlmResponse.create", return_value=mock_llm_res):
        mock_gen.return_value = MagicMock()

        events = []
        async for event in runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=user_message,
        ):
            events.append(event)

    # 1. Kiểm tra session state đã khởi tạo active_section = feature_definition
    updated_session = await session_service.get_session(
        app_name="ba_agent_test",
        user_id="test_user",
        session_id=session.id,
    )
    assert updated_session.state.get("active_section") == "feature_definition"

    # 2. Kiểm tra events được sinh ra từ graph execution
    assert len(events) > 0
