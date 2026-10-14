"""History windowing callback for conversation context management.

Provides a factory function that creates a ``before_model_callback`` to filter
and slice conversation history before sending to the LLM.

Two modes:
  * ``process_latest_message_only=True``:  Keep only the last user message.
  * Full filtering: parse events into turns, filter by author allowlists,
    remove unwanted author turns, and slice to a max turn window.

Usage::

    from chatbot.callbacks.before_model_callbacks import create_history_filter

    LlmAgent(
        name="sale_agent",
        before_model_callback=[
            create_history_filter(
                visible_authors=["sale_agent"],
                remove_turn_of_authors=["greeting_agent", "spam_agent"],
            ),
            # ... other callbacks
        ],
    )
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable  # noqa: UP035

from google.adk.agents.callback_context import CallbackContext
from google.adk.events import Event
from google.adk.models.llm_request import LlmRequest

from config.base_config import settings

# ── Turn data structure ─────────────────────────────────────────────────


@dataclass
class Turn:
    """A single conversation turn: user message + subsequent model/tool events."""

    user_event: Event | None = None
    model_events: list[Event] = field(default_factory=list)

    @property
    def events(self) -> list[Event]:
        """Return all events in chronological order."""
        if self.user_event:
            return [self.user_event] + self.model_events
        return list(self.model_events)

    def has_author_in(self, authors_to_remove: set[str]) -> bool:
        """Check whether any model event was authored by an agent to be removed."""
        return any(e.author in authors_to_remove for e in self.model_events)


# ── Internal helpers ────────────────────────────────────────────────────


def _is_real_user_event(event: Event) -> bool:
    """Check if a user event is a real user message, not ADK-internal.

    Filters out:
    - Branch-scoped copies from fan-out (event.branch is set, e.g. 'fd_extractor@1')
    - JoinNode synthetic outputs (invocation_id is empty string)
    """
    if event.branch:
        return False
    if not event.invocation_id:
        return False
    return True


def _parse_into_turns(
    session_events: list[Event],
    authors: list[str],
    tools: list[str],
) -> list[Turn]:
    """Parse session events into a chronological list of Turn objects.

    Each Turn starts with a user message and includes subsequent model/tool
    events until the next user message. Events are filtered by author and tool
    allowlists during parsing.

    ## Args:
        session_events: The full timeline list of session events.
        authors: The agent names whose model text events should be retained.
        tools: The valid tool names to include in history.

    ## Returns:
        Chronological list of parsed conversation turns.
    """
    turns: list[Turn] = []
    current = Turn()

    for event in session_events:
        if event.content is None or not event.content.parts:
            continue

        part = event.content.parts[0]

        # Ensure single-part (deep copy to avoid mutating original)
        if part.text and len(event.content.parts) != 1:
            event = deepcopy(event)
            event.content.parts = [part]

        # Function call — only keep if tool matches
        func_call = part.function_call
        if func_call:
            if func_call.name in tools:
                current.model_events.append(event)
            continue

        # Function response — only keep if tool matches
        func_response = part.function_response
        if func_response:
            if func_response.name in tools:
                current.model_events.append(event)
            continue

        # Text event
        text = part.text
        if not text:
            continue

        if event.content.role == "user":
            # Skip ADK-internal user events (branch copies, JoinNode outputs)
            if not _is_real_user_event(event):
                continue
            # Flush previous turn if it has content
            if current.user_event is not None or current.model_events:
                turns.append(current)
            current = Turn(user_event=event)

        elif event.content.role == "model":
            # Keep model events from allowed authors
            if event.author in authors:
                current.model_events.append(event)

    # Flush last turn
    if current.user_event is not None or current.model_events:
        turns.append(current)

    return turns


def _filter_events(
    authors: list[str],
    tools: list[str],
    session_events: list[Event],
    max_turns: int = 8,
    remove_turn_of_authors: set[str] | None = None,
) -> list[Event]:
    """Filter and slice session events into a windowed conversation history.

    Two-pass approach:
      1. Parse all events into Turn objects (chronological)
      2. Take the last N valid turns (skip turns from removed authors)

    ## Args:
        authors: Agent names whose model text events should be retained.
        tools: Valid tool names to include in history.
        session_events: The full timeline list of session events.
        max_turns: Number of conversation turns to keep. Defaults to 8.
        remove_turn_of_authors: Agent names whose turns should be dropped entirely.

    ## Returns:
        A sliced and filtered list of Events.
    """
    max_turns = max_turns if max_turns >= 0 else 8
    remove_authors = remove_turn_of_authors or set()

    # Pass 1: Parse events into turns
    turns = _parse_into_turns(session_events, authors, tools)

    # Pass 2: Collect last max_turns valid turns (reverse, skip removed).
    # Drop orphan user-only turns (e.g. FD chat while filtering for br_discussion)
    # so section switches do not inflate the prompt with unrelated history.
    # Always keep the latest turn if it has a user message (current input).
    valid_turns: list[Turn] = []
    latest_idx = len(turns) - 1
    for idx in range(latest_idx, -1, -1):
        turn = turns[idx]
        if remove_authors and turn.has_author_in(remove_authors):
            continue
        is_latest = idx == latest_idx
        has_visible_reply = any(
            getattr(e, "author", None) in authors for e in turn.model_events
        )
        if not has_visible_reply and not (is_latest and turn.user_event is not None):
            continue
        valid_turns.insert(0, turn)
        if len(valid_turns) >= max_turns:
            break

    # Flatten turns into event list
    result: list[Event] = []
    for turn in valid_turns:
        result.extend(turn.events)

    return result


# ── Public factory ──────────────────────────────────────────────────────


def create_history_filter(
    visible_authors: list[str] | None = None,
    remove_turn_of_authors: list[str] | None = None,
    max_turns: int = settings.slice_history,
    process_latest_message_only: bool = False,
) -> Callable:
    """Create a ``before_model_callback`` that filters conversation history.

    ## Args:
        visible_authors: Agent names whose model text events are kept.
            None or [] means no model events are retained.
        remove_turn_of_authors: Agent names whose entire turns are dropped
            (both user message and model response).
        max_turns: Maximum number of turns to keep in the window.
        process_latest_message_only: If True, discard all history and keep
            only the most recent user message.

    ## Returns:
        A callback function compatible with LlmAgent's ``before_model_callback``.
    """
    _authors = list(visible_authors or [])
    _remove = set(remove_turn_of_authors or [])

    def _filter_history(
        callback_context: CallbackContext, llm_request: LlmRequest
    ) -> None:
        session_events = callback_context.session.events

        if process_latest_message_only:
            # Keep only the last real user content
            for event in reversed(session_events):
                if event.content and event.content.role == "user":
                    # Skip ADK-internal user events (branch copies, JoinNode outputs)
                    if not _is_real_user_event(event):
                        continue
                    # Skip if any part is a function response
                    if any(part.function_response for part in event.content.parts):
                        continue
                    llm_request.contents = [event.content]
                    return
            llm_request.contents = []
            return

        # Get tool names from agent
        inv_ctx = callback_context.get_invocation_context()
        tools = [
            getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))
            for tool in inv_ctx.agent.tools
        ]

        # Filter and slice events
        filtered = _filter_events(
            authors=_authors,
            tools=tools,
            session_events=session_events,
            max_turns=max_turns,
            remove_turn_of_authors=_remove,
        )

        # Replace LLM contents with filtered event contents
        llm_request.contents = [e.content for e in filtered if e.content]

    return _filter_history
