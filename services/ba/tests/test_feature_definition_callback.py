"""Unit tests for Feature Definition callbacks."""

import pytest
from unittest.mock import MagicMock
from google.adk.agents.callback_context import CallbackContext

from agents.sub_graph.feature_definition.nodes.extractor.callback import fd_merge_callback


@pytest.mark.anyio
async def test_fd_merge_callback_basic():
    """Test merging FD data into state via fd_merge_callback."""
    mock_context = MagicMock(spec=CallbackContext)
    mock_context.state = {}

    mock_response = MagicMock()
    mock_response.content.parts[0].text = """{
        "goal": "Tự động hóa phân tích BA",
        "actors": ["Product Owner", "BA Agent"],
        "scope_in": ["Quản lý 9 sections"],
        "scope_out": ["Tự động sinh code backend"]
    }"""

    await fd_merge_callback(mock_context, mock_response)

    artifact = mock_context.state["artifacts"]["feature_definition"]
    assert artifact["goal"] == "Tự động hóa phân tích BA"
    assert len(artifact["actors"]) == 2
    assert len(artifact["scope_in"]) == 1
    assert len(artifact["scope_out"]) == 1


@pytest.mark.anyio
async def test_fd_merge_callback_markdown_text():
    """Test merging FD data when llm_response text contains markdown ```json block."""
    mock_context = MagicMock(spec=CallbackContext)
    mock_context.state = {}

    mock_response = MagicMock()
    mock_response.content.parts[0].text = """```json
{
  "goal": "Thanh toán ví MoMo tiện lợi",
  "actors": ["Khách hàng", "MoMo Gateway"],
  "scope_in": ["Tạo giao dịch"],
  "scope_out": []
}
```"""

    await fd_merge_callback(mock_context, mock_response)

    artifact = mock_context.state["artifacts"]["feature_definition"]
    assert artifact["goal"] == "Thanh toán ví MoMo tiện lợi"
    assert artifact["actors"][0].startswith("ACT-")
    assert "Khách hàng" in artifact["actors"][0]
    assert "MoMo Gateway" in artifact["actors"][1]
    assert len(artifact["actors"]) == 2
