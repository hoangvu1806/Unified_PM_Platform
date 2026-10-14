"""ADK Runtime Context — one Runner, one SessionService, one BA graph.

Ticket type is session state, not a separate Runner. ``get_runner(ticket_type)``
still validates the enum so the V1 API contract stays stable.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService

from agents.ba_agent.agent import create_ba_agent
from agents.ba_agent.constants import SUPPORTED_TICKET_TYPES
from config.base_config import settings
from managers.database.package_repository import BaPackageRepository

logger = logging.getLogger(__name__)

APP_NAME = "ba-agent"
RUNNER_NOT_INITIALIZED = "ADK Runner not initialized"

_session_service: DatabaseSessionService | None = None
_runner: Runner | None = None


async def init_adk() -> None:
    """Initialize ADK session service and the single unified BA runner."""
    global _session_service, _runner  # noqa: PLW0603

    db_repository = BaPackageRepository()
    db_repository.init_tables()

    _session_service = DatabaseSessionService(
        db_url=settings.database_url, **settings.async_engine_kwargs
    )
    _runner = Runner(
        app_name=APP_NAME,
        agent=create_ba_agent(),
        session_service=_session_service,
    )
    logger.info(
        "ADK unified BA Runner initialized (ticket types: %s)",
        sorted(SUPPORTED_TICKET_TYPES),
    )


def get_runner(ticket_type: str = "NEW_FEATURE") -> Runner:
    """Return the unified BA Runner after validating ticket_type.

    Raises:
        HTTPException 503: ADK not initialized.
        HTTPException 400: Ticket type not in the supported enum.
    """
    if _runner is None:
        raise HTTPException(status_code=503, detail=RUNNER_NOT_INITIALIZED)

    if ticket_type not in SUPPORTED_TICKET_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Ticket type '{ticket_type}' chưa được hỗ trợ. "
                f"Các loại hỗ trợ: {sorted(SUPPORTED_TICKET_TYPES)}"
            ),
        )
    return _runner


def get_session_service() -> DatabaseSessionService:
    """Return the ADK SessionService or raise HTTP 503 if not yet initialized."""
    if _session_service is None:
        raise HTTPException(
            status_code=503, detail="ADK SessionService not initialized"
        )
    return _session_service


def sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a single Server-Sent Event string."""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
