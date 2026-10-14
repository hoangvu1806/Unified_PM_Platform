"""Plain HTTP for Validation Agent — JS fetch, no ADK graph required."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException

from managers.control.session import CONTROL_USER_ID, load_control_state
from managers.control.va_service import execute_va_turn, hydrate_package_into_state
from managers.service.state_helpers import build_state_update_payload

router = APIRouter(prefix="/api/va", tags=["Validate Agent"])


class VaMessageRequest(BaseModel):
    user_id: str = Field(default=CONTROL_USER_ID, min_length=1)
    user_message: str = Field(default="", description="Discuss the last report")


class VaValidateRequest(BaseModel):
    user_id: str = Field(default=CONTROL_USER_ID, min_length=1)


@router.get("/{session_id}")
async def get_va_snapshot(session_id: str):
    """Last report + readiness. Does not run the ADK graph."""
    try:
        state = await load_control_state(session_id)
    except HTTPException:
        raise
    hydrate_package_into_state(state, session_id)
    payload = build_state_update_payload(state)
    last = state.get("last_validation") or state.get("_va_result") or {}
    return {
        "runtime": "plain",
        "session_id": session_id,
        "feature_status": payload.get("feature_status"),
        "can_proceed_to_validation": payload.get("can_proceed_to_validation"),
        "last_validation": last if isinstance(last, dict) else {},
        "state": payload,
    }


@router.post("/{session_id}/validate")
async def post_va_validate(session_id: str, req: VaValidateRequest | None = None):
    """Run full VA checks (wiki + cross-section). Plain JSON for the VA page / BA Validate button."""
    body = req or VaValidateRequest()
    return await execute_va_turn(
        session_id,
        user_id=body.user_id,
        user_message="[VALIDATE] Validate BA package",
        run_validate=True,
    )


@router.post("/{session_id}/message")
async def post_va_message(session_id: str, req: VaMessageRequest):
    """Discuss last report. Same engine as validate; no ADK Workflow."""
    text = (req.user_message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="user_message không được để trống")
    run_validate = text.startswith("[VALIDATE]")
    return await execute_va_turn(
        session_id,
        user_id=req.user_id,
        user_message=text,
        run_validate=run_validate,
    )
