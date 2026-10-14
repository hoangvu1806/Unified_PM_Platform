"""Orchestrate an explicit BA -> Designer handoff."""

from __future__ import annotations

from typing import Any

from .client import DesignerClient
from .mapper import build_designer_handoff


async def send_to_designer(envelope: dict[str, Any], *, base_url: str, timeout_seconds: float, shared_secret: str = "") -> dict:
    payload = build_designer_handoff(envelope)
    result = await DesignerClient(base_url, timeout_seconds, shared_secret).create_handoff(payload)
    return {"request": payload, "response": result}
