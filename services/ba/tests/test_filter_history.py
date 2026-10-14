"""Tests for callbacks/filter_history.py — ADK Workflow event filtering."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from callbacks.filter_history import _is_real_user_event, _parse_into_turns


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_event(
    *,
    role: str = "user",
    text: str = "hello",
    author: str = "user",
    branch: str | None = None,
    invocation_id: str = "e-abc-123",
) -> MagicMock:
    """Create a mock Event with the fields used by filter_history."""
    event = MagicMock()
    event.author = author
    event.branch = branch
    event.invocation_id = invocation_id

    part = MagicMock()
    part.text = text
    part.function_call = None
    part.function_response = None

    content = MagicMock()
    content.role = role
    content.parts = [part]

    event.content = content
    return event


# ── _is_real_user_event ────────────────────────────────────────────────


class TestIsRealUserEvent:
    """Tests for the _is_real_user_event helper."""

    def test_real_user_event(self):
        event = _make_event(branch=None, invocation_id="e-abc-123")
        assert _is_real_user_event(event) is True

    def test_branch_scoped_copy(self):
        """Fan-out branch copies should be filtered out."""
        event = _make_event(branch="fd_extractor@1", invocation_id="e-abc-123")
        assert _is_real_user_event(event) is False

    def test_join_node_synthetic(self):
        """JoinNode synthetic events have empty invocation_id."""
        event = _make_event(branch=None, invocation_id="")
        assert _is_real_user_event(event) is False

    def test_branch_and_empty_invocation(self):
        """Both signals present → not real."""
        event = _make_event(branch="oq_asm_detector@1", invocation_id="")
        assert _is_real_user_event(event) is False


# ── _parse_into_turns ──────────────────────────────────────────────────


class TestParseIntoTurns:
    """Tests for _parse_into_turns with Workflow event topologies."""

    def test_flat_conversation(self):
        """Simple user → model → user → model should produce 2 turns."""
        events = [
            _make_event(role="user", text="msg1", author="user"),
            _make_event(role="model", text="reply1", author="fd_discussion"),
            _make_event(role="user", text="msg2", author="user"),
            _make_event(role="model", text="reply2", author="fd_discussion"),
        ]

        turns = _parse_into_turns(events, authors=["fd_discussion"], tools=[])
        assert len(turns) == 2

        # Turn 1
        assert turns[0].user_event.content.parts[0].text == "msg1"
        assert len(turns[0].model_events) == 1
        assert turns[0].model_events[0].content.parts[0].text == "reply1"

        # Turn 2
        assert turns[1].user_event.content.parts[0].text == "msg2"
        assert len(turns[1].model_events) == 1

    def test_branch_copies_filtered(self):
        """Fan-out branch copies of user messages should be skipped."""
        events = [
            _make_event(role="user", text="msg1", author="user", branch=None),
            _make_event(role="user", text="msg1", author="user", branch="fd_extractor@1"),
            _make_event(role="user", text="msg1", author="user", branch="oq_asm_detector@1"),
            _make_event(role="model", text="reply1", author="fd_discussion", branch=None),
        ]

        turns = _parse_into_turns(events, authors=["fd_discussion"], tools=[])
        assert len(turns) == 1
        assert turns[0].user_event.content.parts[0].text == "msg1"
        assert len(turns[0].model_events) == 1

    def test_join_node_synthetic_filtered(self):
        """JoinNode synthetic user events (empty invocation_id) should be skipped."""
        events = [
            _make_event(role="user", text="msg1", author="user"),
            _make_event(role="model", text="reply1", author="fd_discussion"),
            _make_event(
                role="user",
                text='{"fd_flags_checker": {}, "oq_asm_detector": {}}',
                author="user",
                invocation_id="",
            ),
        ]

        turns = _parse_into_turns(events, authors=["fd_discussion"], tools=[])
        assert len(turns) == 1
        assert turns[0].user_event.content.parts[0].text == "msg1"
        assert len(turns[0].model_events) == 1

    def test_workflow_full_topology(self):
        """Simulate a real 2-turn Workflow with fan-out + JoinNode events.

        Turn 1: user msg → [branch copies, extractor, detector, flags_checker, join] → fd_discussion reply
        Turn 2: user msg → [branch copies, extractor, detector, flags_checker, join] → (about to call fd_discussion)
        """
        events = [
            # --- Turn 1 ---
            _make_event(role="user", text="Feature MoMo", author="user", invocation_id="e-inv-1"),
            # Extractor branch copy
            _make_event(role="user", text="Feature MoMo", author="user", branch="fd_extractor@1", invocation_id=""),
            # Detector branch copy
            _make_event(role="user", text="Feature MoMo", author="user", branch="oq_asm_detector@1", invocation_id=""),
            # Extractor model response (filtered by visible_authors)
            _make_event(role="model", text='{"goal":"MoMo"}', author="fd_extractor", branch="fd_extractor@1"),
            # Detector model response (filtered)
            _make_event(role="model", text='{"open_questions":[]}', author="oq_asm_detector", branch="oq_asm_detector@1"),
            # JoinNode output
            _make_event(role="user", text='{"fd_flags_checker":{}}', author="user", invocation_id=""),
            # fd_discussion reply
            _make_event(role="model", text="Chào bạn!", author="fd_discussion"),
            # --- Turn 2 ---
            _make_event(role="user", text="chọn gợi ý", author="user", invocation_id="e-inv-2"),
            _make_event(role="user", text="chọn gợi ý", author="user", branch="fd_extractor@1", invocation_id=""),
            _make_event(role="user", text="chọn gợi ý", author="user", branch="oq_asm_detector@1", invocation_id=""),
            _make_event(role="model", text='{"goal":""}', author="fd_extractor", branch="fd_extractor@1"),
            _make_event(role="model", text='{"open_questions":[]}', author="oq_asm_detector", branch="oq_asm_detector@1"),
            _make_event(role="user", text='{"fd_flags_checker":{}}', author="user", invocation_id=""),
        ]

        turns = _parse_into_turns(events, authors=["fd_discussion"], tools=[])

        # Should produce exactly 2 turns
        assert len(turns) == 2

        # Turn 1: real user msg + fd_discussion reply
        assert turns[0].user_event.content.parts[0].text == "Feature MoMo"
        assert len(turns[0].model_events) == 1
        assert turns[0].model_events[0].content.parts[0].text == "Chào bạn!"

        # Turn 2: real user msg, no fd_discussion reply yet
        assert turns[1].user_event.content.parts[0].text == "chọn gợi ý"
        assert len(turns[1].model_events) == 0

    def test_other_authors_filtered(self):
        """Model events from non-visible authors should be dropped."""
        events = [
            _make_event(role="user", text="msg1", author="user"),
            _make_event(role="model", text="extractor output", author="fd_extractor"),
            _make_event(role="model", text="discussion reply", author="fd_discussion"),
        ]

        turns = _parse_into_turns(events, authors=["fd_discussion"], tools=[])
        assert len(turns) == 1
        assert len(turns[0].model_events) == 1
        assert turns[0].model_events[0].author == "fd_discussion"

    def test_empty_events(self):
        """Empty event list should produce no turns."""
        turns = _parse_into_turns([], authors=["fd_discussion"], tools=[])
        assert len(turns) == 0

    def test_no_content_events_skipped(self):
        """Events with content=None should be skipped."""
        event_no_content = MagicMock()
        event_no_content.content = None

        turns = _parse_into_turns([event_no_content], authors=["fd_discussion"], tools=[])
        assert len(turns) == 0


class TestFilterEvents:
    def test_drops_orphan_fd_turns_when_filtering_br(self):
        from callbacks.filter_history import _filter_events

        events = [
            _make_event(role="user", text="fd1", author="user"),
            _make_event(role="model", text="fd reply", author="fd_discussion"),
            _make_event(role="user", text="fd2", author="user"),
            _make_event(role="model", text="fd reply2", author="fd_discussion"),
            _make_event(role="user", text="br start", author="user"),
        ]
        filtered = _filter_events(
            authors=["br_discussion"],
            tools=[],
            session_events=events,
            max_turns=5,
        )
        texts = [e.content.parts[0].text for e in filtered]
        assert texts == ["br start"]
