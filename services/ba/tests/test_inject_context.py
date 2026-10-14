from unittest.mock import MagicMock

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest
from google.genai import types

from callbacks.inject_context import inject_artifact_context
from callbacks.utils import extract_session_id
from managers.database.package_repository import BaPackageRepository


def test_extract_session_id() -> None:
    # Test removing agent prefix
    raw_session = "/ba-agent/feature_definition/test_session_123"
    agent = "feature_definition"
    assert extract_session_id(raw_session, agent) == "test_session_123"

    # Test when no prefix exists
    assert extract_session_id("plain_session", agent) == "plain_session"
    assert extract_session_id("", agent) == ""


def test_inject_artifact_context_creates_empty_section_if_missing(tmp_path) -> None:
    repo = BaPackageRepository()
    session_id = "sess_test_missing_section"

    # Ensure section does not exist
    assert repo.get_section(session_id, "business_rules") is None

    callback_func = inject_artifact_context(
        sections=["business_rules"], db_repository=repo
    )

    ctx_state = {
        "session_id": f"/ba-agent/business_rules/{session_id}",
        "select_agent": "business_rules",
    }
    mock_ctx = MagicMock(spec=CallbackContext)
    mock_ctx.state = ctx_state

    user_content = types.Content(
        role="user", parts=[types.Part.from_text(text="User question")]
    )
    llm_req = LlmRequest(contents=[user_content])

    # Run callback
    callback_func(mock_ctx, llm_req)

    # 1. Verify DB record was created with empty dict
    db_section = repo.get_section(session_id, "business_rules")
    assert db_section == {}

    # 2. Verify context message was inserted into llm_req before user message
    assert len(llm_req.contents) == 2
    assert llm_req.contents[0].role == "user"
    assert "=== CURRENT DATA OF business_rules ===" in llm_req.contents[0].parts[0].text
    assert "{}" in llm_req.contents[0].parts[0].text
    assert llm_req.contents[1].parts[0].text == "User question"


def test_inject_artifact_context_with_existing_data(tmp_path) -> None:
    repo = BaPackageRepository()
    session_id = "sess_test_existing_data"

    # Save existing section data into DB
    initial_data = {"rule_1": "Rule A description"}
    repo.save_section(
        session_id=session_id,
        section_id="business_rules",
        data=initial_data,
        flags={"BR_F1": "PASS"},
        is_completable=True,
    )

    callback_func = inject_artifact_context(
        sections=["business_rules"], db_repository=repo
    )

    ctx_state = {
        "session_id": session_id,
        "select_agent": "",
    }
    mock_ctx = MagicMock(spec=CallbackContext)
    mock_ctx.state = ctx_state

    user_content = types.Content(
        role="user", parts=[types.Part.from_text(text="Check rules")]
    )
    llm_req = LlmRequest(contents=[user_content])

    callback_func(mock_ctx, llm_req)

    assert len(llm_req.contents) == 2
    assert "Rule A description" in llm_req.contents[0].parts[0].text
