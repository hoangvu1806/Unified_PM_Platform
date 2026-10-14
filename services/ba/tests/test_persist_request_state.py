"""Regression: active_section must go through run_async state_delta."""

from __future__ import annotations

from unittest.mock import MagicMock

from managers.service.state_helpers import request_state_delta


def test_request_state_delta_includes_active_section():
    req = MagicMock()
    req.active_section = "business_rules"
    req.ticket_type.value = "NEW_FEATURE"
    req.action = None

    delta = request_state_delta(req)
    assert delta["active_section"] == "business_rules"
    assert delta["ticket_type"] == "NEW_FEATURE"
