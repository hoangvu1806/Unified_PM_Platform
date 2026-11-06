"""FastAPI Router and endpoint handlers for API V1 Chat.

Routes:
- POST /{session_id}/message — Sync JSON response
- POST /{session_id}/stream  — SSE streaming response
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from google.genai import types

from agents.ba_agent.constants import (
    DEFAULT_SECTION,
    SECTION_OPEN_QUESTIONS,
    STATE_ACTIVE_SECTION,
    STATE_TICKET_TYPE,
)
from agents.ba_agent.open_questions import format_open_questions_reply
from managers.runner_context import APP_NAME, get_runner, get_session_service, sse_event
from managers.service.schema import AgentChatRequest, AgentChatResponse, ChatAction
from managers.control.session import load_control_state, persist_control_delta
from managers.control.status import is_chat_frozen, package_was_exported
from managers.service.state_helpers import (
    apply_request_to_session_state,
    build_section_status,
    build_state_update_payload,
    is_user_facing_author,
    persist_session_artifacts,
    request_state_delta,
)
from utils import logging

logger = logging()

router = APIRouter(prefix="/api/v1/chat", tags=["Unify AI Agent - V1"])
TURN_TIMEOUT_SECONDS = 300
OQ_TURN_TIMEOUT_SECONDS = 900


def _validate_chat_input(session_id: str, req: AgentChatRequest) -> None:
    """Validate request inputs before processing."""
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id không được để trống")

    if not req.user_message or not req.user_message.strip():
        raise HTTPException(status_code=400, detail="user_message không được để trống")


async def _reject_if_chat_frozen(
    session_id: str,
    user_id: str,
    req: AgentChatRequest,
) -> None:
    """First Export freezes chat send. Validate (and later Export) may still refresh."""
    try:
        state = await load_control_state(session_id, user_id)
    except HTTPException as exc:
        if exc.status_code == 503:
            raise
        return
    if req.action == ChatAction.VALIDATE:
        return
    if (req.active_section or "").strip().lower() == "validation":
        return
    if is_chat_frozen(state.get("feature_status"), package_was_exported(state)):
        raise HTTPException(
            status_code=409,
            detail="Feature chat is frozen after Export. Validate and Export can still refresh against wiki.",
        )


async def _persist_latest_state(session_service, user_id: str, session_id: str) -> dict:
    """Reconcile completed ADK node state to BA package rows, even after failure."""
    updated = await session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )
    state = updated.state if updated else {}
    from managers.control.bpmn import ensure_bpmn_artifact
    from managers.control.session import persist_control_delta
    from managers.control.status import is_readonly
    from managers.control.touchpoints import ensure_touchpoints_artifact

    if state and not is_readonly(state.get("feature_status")):
        artifacts = state.get("artifacts") or {}
        had_bpmn = bool((artifacts.get("bpmn_reference") or {}).get("bpmn_xml_content"))
        existing_tp = artifacts.get("ui_touchpoints")
        if isinstance(existing_tp, dict):
            existing_tp = existing_tp.get("ui_touchpoints") or []
        had_tp = bool(existing_tp)
        bpmn = ensure_bpmn_artifact(state)
        tps = ensure_touchpoints_artifact(state)
        if (bpmn and not had_bpmn) or (tps and not had_tp):
            try:
                await persist_control_delta(
                    session_id,
                    {"artifacts": state.get("artifacts") or {}},
                    user_id=user_id,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to persist Group 2 artifacts: {e}")
    persist_session_artifacts(state, session_id)
    return state


@router.post("/{session_id}/message", response_model=AgentChatResponse)
async def chat_message_sync(session_id: str, req: AgentChatRequest):
    """Send a message to the BA Agent graph and receive a single JSON response object."""

    _validate_chat_input(session_id, req)

    ticket_type = req.ticket_type.value
    user_id = req.user_id or "default-user"
    user_message = req.user_message

    runner = get_runner(ticket_type)
    await _reject_if_chat_frozen(session_id, user_id, req)
    session_service = get_session_service()

    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )
    if not session:
        session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
            state={
                "session_id": session_id,
                STATE_TICKET_TYPE: ticket_type,
                STATE_ACTIVE_SECTION: DEFAULT_SECTION,
            },
        )
    else:
        session.state[STATE_TICKET_TYPE] = ticket_type
        session.state.setdefault(STATE_ACTIVE_SECTION, DEFAULT_SECTION)
        session.state.setdefault("session_id", session_id)

    apply_request_to_session_state(session.state, req)
    state_delta = request_state_delta(req)

    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message)],
    )

    agent_text = ""
    state: dict = {}
    try:
        turn_timeout = (
            OQ_TURN_TIMEOUT_SECONDS
            if req.active_section == SECTION_OPEN_QUESTIONS
            else TURN_TIMEOUT_SECONDS
        )
        async with asyncio.timeout(turn_timeout):
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=content,
                state_delta=state_delta or None,
            ):
                if (
                    event.content
                    and event.content.parts
                    and is_user_facing_author(getattr(event, "author", None))
                ):
                    agent_text = "\n\n".join(
                        p.text for p in event.content.parts if p.text
                    )

    except TimeoutError:
        logger.error(f"V1 Sync Agent graph exceeded {turn_timeout}s")
        raise HTTPException(status_code=504, detail="BA workflow timed out")
    except Exception as e:  # noqa: BLE001
        logger.error(f"V1 Sync Agent graph pipeline error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            state = await asyncio.shield(
                _persist_latest_state(session_service, user_id, session_id)
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to persist session artifacts: {e}")

    section_status, extra_data = build_section_status(state)
    if not agent_text:
        last = state.get("last_validation") or state.get("_va_result") or {}
        agent_text = str(last.get("agent_response") or "")

    return AgentChatResponse(
        session_id=session_id,
        user_id=user_id,
        ticket_type=req.ticket_type,
        agent_response=agent_text,
        section_status=section_status,
        extra_data=extra_data,
    )


@router.post("/{session_id}/stream")
async def chat_message_stream(session_id: str, req: AgentChatRequest):
    """Send a message to the BA Agent graph and stream response events via SSE."""
    _validate_chat_input(session_id, req)

    user_id = req.user_id or "default-user"
    runner = get_runner(req.ticket_type.value)
    await _reject_if_chat_frozen(session_id, user_id, req)
    session_service = get_session_service()

    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )
    if not session:
        session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
            state={
                "session_id": session_id,
                STATE_TICKET_TYPE: req.ticket_type.value,
                STATE_ACTIVE_SECTION: DEFAULT_SECTION,
            },
        )
    else:
        session.state[STATE_TICKET_TYPE] = req.ticket_type.value
        session.state.setdefault(STATE_ACTIVE_SECTION, DEFAULT_SECTION)
        session.state.setdefault("session_id", session_id)

    apply_request_to_session_state(session.state, req)
    state_delta = request_state_delta(req)
    if req.active_section == SECTION_OPEN_QUESTIONS:
        expected_turn = int(session.state.get("current_turn", 0)) + 1
        # Persist before returning the stream so history polling knows this turn
        # is active and does not synthesize a premature completion message.
        await persist_control_delta(
            session_id,
            {
                "_oq_stream_active_turn": expected_turn,
                "_oq_stream_completed_turn": None,
            },
            user_id=user_id,
        )

    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=req.user_message)],
    )

    async def event_generator():
        state: dict = {}
        error_message: str | None = None
        emitted_text = False
        stream_ended = False
        try:
            turn_timeout = (
                OQ_TURN_TIMEOUT_SECONDS
                if req.active_section == SECTION_OPEN_QUESTIONS
                else TURN_TIMEOUT_SECONDS
            )
            async with asyncio.timeout(turn_timeout):
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=content,
                    state_delta=state_delta or None,
                ):
                    if (
                        event.content
                        and event.content.parts
                        and is_user_facing_author(getattr(event, "author", None))
                    ):
                        for part in event.content.parts:
                            if part.text:
                                emitted_text = True
                                yield sse_event(
                                    "chat.message",
                                    {"sender": "agent", "text": part.text},
                                )
            stream_ended = True
        except TimeoutError:
            error_message = f"BA workflow exceeded {turn_timeout} seconds"
            stream_ended = True
            logger.error("V1 Stream Agent graph timed out")
        except asyncio.CancelledError:
            logger.warning("V1 Stream client disconnected; preserving partial state")
            stream_ended = True
            raise
        except Exception as e:  # noqa: BLE001
            error_message = str(e)
            stream_ended = True
            logger.error(f"V1 Stream Agent graph pipeline error: {e}")
        finally:
            try:
                state = await asyncio.shield(
                    _persist_latest_state(session_service, user_id, session_id)
                )
                if req.active_section == SECTION_OPEN_QUESTIONS and stream_ended:
                    state = await persist_control_delta(
                        session_id,
                        {
                            "_oq_stream_completed_turn": state.get("current_turn"),
                            "_oq_stream_active_turn": None,
                        },
                        user_id=user_id,
                    )
                if error_message and req.active_section == SECTION_OPEN_QUESTIONS:
                    questions = list(state.get("open_questions") or [])
                    current_oq_id = str(state.get("_oq_sync_current_id") or "").upper()
                    for question in questions:
                        if (
                            str(question.get("id") or "").upper() == current_oq_id
                            and current_oq_id
                            and question.get("status") == "resolved"
                            and question.get("sync_status") == "pending"
                        ):
                            question["sync_status"] = "failed"
                    pending_ids = [
                        str(question.get("id") or "OQ")
                        for question in questions
                        if question.get("status") == "resolved"
                        and question.get("sync_status") in {"pending", "failed"}
                    ]
                    if pending_ids:
                        state["open_questions"] = questions
                        prior_result = state.get("_oq_sync_result") or {}
                        if prior_result.get("turn") != state.get("current_turn"):
                            prior_result = {}
                        errors = list(prior_result.get("errors") or [])
                        if error_message not in errors:
                            errors.append(error_message)
                        state["_oq_sync_result"] = {
                            "turn": state.get("current_turn"),
                            "pending_oq_ids": pending_ids,
                            "errors": errors,
                            "updated_artifacts": list(prior_result.get("updated_artifacts") or []),
                            "review": prior_result.get("review") or state.get("_ba_change_review") or {},
                        }
                        try:
                            state = await persist_control_delta(
                                session_id,
                                {
                                    "open_questions": questions,
                                    "_oq_sync_queue": state.get("_oq_sync_queue") or [],
                                    "_oq_sync_result": state["_oq_sync_result"],
                                },
                                user_id=user_id,
                            )
                        except Exception as persist_error:  # noqa: BLE001
                            logger.warning(
                                f"Failed to persist OQ sync failure state: {persist_error}"
                            )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to persist session artifacts: {e}")

        if not emitted_text:
            if req.active_section == SECTION_OPEN_QUESTIONS:
                report = format_open_questions_reply(state or {})
            else:
                last = (state or {}).get("last_validation") or (state or {}).get("_va_result") or {}
                report = str(last.get("agent_response") or "")
            if report:
                yield sse_event("chat.message", {"sender": "agent", "text": report})
            else:
                logger.warning(
                    f"V1 Stream completed without a user-facing reply: "
                    f"session={session_id} section={req.active_section}"
                )
        if state:
            yield sse_event("state.update", build_state_update_payload(state))
        if error_message:
            yield sse_event("chat.error", {"error": error_message})
        else:
            yield sse_event("chat.done", {})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
