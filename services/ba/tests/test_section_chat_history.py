from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.ba_agent.constants import (
    AUTHOR_BA_LOCKED,
    AUTHOR_BA_NOT_READY,
    AUTHOR_WF_DISCUSSION,
    SECTION_BUSINESS_RULES,
    SECTION_WORKFLOW,
    STATE_ACTIVE_SECTION,
)
from managers.service import features


def _event(author=None, text=None, *, role="model", state_delta=None):
    content = None
    if text is not None:
        content = SimpleNamespace(
            role=role,
            parts=[SimpleNamespace(text=text)],
        )
    return SimpleNamespace(
        author=author,
        content=content,
        actions=SimpleNamespace(state_delta=state_delta or {}),
    )


class _SessionService:
    def __init__(self, session):
        self.session = session

    async def get_session(self, **_kwargs):
        return self.session


@pytest.mark.asyncio
async def test_history_is_scoped_to_turn_section_and_keeps_gate_replies(monkeypatch):
    events = [
        _event(state_delta={STATE_ACTIVE_SECTION: SECTION_BUSINESS_RULES}),
        _event(text="Add password rule", role="user"),
        _event(AUTHOR_BA_NOT_READY, "Please clarify the rule"),
        _event(state_delta={STATE_ACTIVE_SECTION: SECTION_WORKFLOW}),
        _event(text="Describe the workflow", role="user"),
        _event(AUTHOR_WF_DISCUSSION, "Workflow response"),
    ]
    session = SimpleNamespace(
        state={STATE_ACTIVE_SECTION: SECTION_WORKFLOW},
        events=events,
    )
    monkeypatch.setattr(features, "get_session_service", lambda: _SessionService(session))

    business_rules = await features.get_chat_history("session", section=SECTION_BUSINESS_RULES)
    workflow = await features.get_chat_history("session", section=SECTION_WORKFLOW)

    assert [(m.sender, m.text) for m in business_rules.messages] == [
        ("user", "Add password rule"),
        ("agent", "Please clarify the rule"),
    ]
    assert [(m.sender, m.text) for m in workflow.messages] == [
        ("user", "Describe the workflow"),
        ("agent", "Workflow response"),
    ]


@pytest.mark.asyncio
async def test_locked_reply_is_kept_for_the_turn_active_section(monkeypatch):
    session = SimpleNamespace(
        state={STATE_ACTIVE_SECTION: SECTION_BUSINESS_RULES},
        events=[
            _event(state_delta={STATE_ACTIVE_SECTION: SECTION_BUSINESS_RULES}),
            _event(text="Go to business rules", role="user"),
            _event(AUTHOR_BA_LOCKED, "This section is locked"),
        ],
    )
    monkeypatch.setattr(features, "get_session_service", lambda: _SessionService(session))

    history = await features.get_chat_history("session", section=SECTION_BUSINESS_RULES)

    assert [(m.sender, m.text) for m in history.messages] == [
        ("user", "Go to business rules"),
        ("agent", "This section is locked"),
    ]
