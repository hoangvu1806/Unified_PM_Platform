"""Unit tests for the unified BA graph router."""

from unittest.mock import MagicMock

from agents.ba_agent.constants import (
    ROUTE_FD,
    ROUTE_LOCKED,
    ROUTE_STUB,
    SECTION_BUSINESS_RULES,
    SECTION_FEATURE_DEFINITION,
    STATE_ACTIVE_SECTION,
    STATE_TICKET_TYPE,
    TICKET_BUG_FIX_LOG,
    TICKET_NEW_FEATURE,
)
from agents.ba_agent.router import route_ba_turn


def _ctx(state: dict, text: str = "hello") -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    ctx.route = None
    part = MagicMock()
    part.text = text
    ctx.user_content.parts = [part]
    return ctx


def test_router_defaults_to_feature_definition():
    ctx = _ctx({})
    route_ba_turn(ctx)
    assert ctx.route == ROUTE_FD
    assert ctx.state[STATE_ACTIVE_SECTION] == SECTION_FEATURE_DEFINITION
    assert ctx.state[STATE_TICKET_TYPE] == TICKET_NEW_FEATURE


def test_router_stubs_unimplemented_ticket():
    ctx = _ctx({STATE_TICKET_TYPE: TICKET_BUG_FIX_LOG})
    route_ba_turn(ctx)
    assert ctx.route == ROUTE_STUB


def test_router_locks_br_without_fd_complete():
    ctx = _ctx(
        {
            STATE_TICKET_TYPE: TICKET_NEW_FEATURE,
            STATE_ACTIVE_SECTION: SECTION_BUSINESS_RULES,
            "flags": {"fd": {"FD-F1": {"status": "MISSING_VALUE"}}},
        }
    )
    route_ba_turn(ctx)
    assert ctx.route == ROUTE_LOCKED
