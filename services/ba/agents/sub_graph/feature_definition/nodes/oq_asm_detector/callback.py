"""Callbacks for OQ & ASM Detector Node."""

from __future__ import annotations

import json
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from agents.sub_graph.feature_definition.schemas import OQASMDetectionData
from callbacks.inject_context import insert_context
from utils import logging
from utils.utils import parse_str_to_dict

logger = logging()

_OQ_ANSWER_RE = re.compile(
    r"(?:trả\s*lời|traloi|answer|resolve)?\s*(OQ-\d{3})\s*[:：\-–]\s*(.+)",
    re.IGNORECASE,
)


def user_text_from_context(callback_context: Any) -> str:
    content = getattr(callback_context, "user_content", None)
    if content is None and hasattr(callback_context, "state"):
        content = callback_context.state.get("_last_user_message")
        if isinstance(content, str):
            return content
    parts = getattr(content, "parts", None) or []
    texts = [str(getattr(part, "text", "") or "") for part in parts]
    return "\n".join(t for t in texts if t).strip()


def resolutions_from_user_message(user_message: str) -> list[dict[str, str]]:
    """Deterministic OQ answers: 'OQ-001: …' or 'Trả lời OQ-001: …'."""
    found: list[dict[str, str]] = []
    if not user_message:
        return found
    seen: set[str] = set()
    for match in _OQ_ANSWER_RE.finditer(user_message):
        oq_id = match.group(1).upper()
        answer = match.group(2).strip()
        if oq_id in seen or len(answer) < 3:
            continue
        seen.add(oq_id)
        found.append({"id": oq_id, "answer": answer, "status": "resolved"})
    return found


def apply_oq_resolutions(state: dict[str, Any], resolutions: list[Any]) -> int:
    """Mark existing OQs resolved. Does not create OQs or waive unanswered ones."""
    if not resolutions:
        return 0
    oqs: list[dict[str, Any]] = list(state.get("open_questions") or [])
    by_id = {str(oq.get("id", "")).upper(): oq for oq in oqs}
    changed = 0
    for raw in resolutions:
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            continue
        oq_id = str(raw.get("id") or "").strip().upper()
        answer = str(raw.get("answer") or "").strip()
        status = str(raw.get("status") or "resolved").strip().lower()
        if status not in {"resolved", "open"}:
            status = "resolved"
        if not oq_id or not answer or oq_id not in by_id:
            continue
        target = by_id[oq_id]
        target["status"] = status
        target["answer"] = answer
        changed += 1
        logger.info(f"oq_asm_merge_callback: {oq_id} → {status}")
    if changed:
        state["open_questions"] = oqs
    return changed


async def oq_asm_merge_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> None:
    """
    Callback xử lý output từ LLM.
    Merge Open Questions (OQ) và Assumptions (ASM) vào state.
    Lưu ý: Hiện tại chỉ merge OQ và ASM, chưa xử lý artifacts.
    """
    parsed: OQASMDetectionData | None = None

    raw_text = llm_response.content.parts[0].text
    parsed_dict = parse_str_to_dict(raw_text)
    if parsed_dict:
        try:
            parsed = OQASMDetectionData.model_validate(parsed_dict)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"oq_asm_merge_callback: Failed to validate dict from text: {e}"
            )

    if not parsed:
        logger.warning("oq_asm_merge_callback: llm_response.parsed is null or invalid")
        return

    state = callback_context.state
    current_turn = state.get("current_turn", 1)
    active_sec = state.get("active_section", "feature_definition")

    # Merge Open Questions (Max 3 new per turn)
    apply_oq_resolutions(state, list(parsed.resolved_questions or []))
    apply_oq_resolutions(state, resolutions_from_user_message(user_text_from_context(callback_context)))

    if parsed.open_questions:
        oqs: list[dict[str, Any]] = list(state.get("open_questions", []))
        existing_questions = {str(oq.get("question", "")).strip().lower() for oq in oqs}
        for item in parsed.open_questions[:3]:
            q_clean = item.question.strip().lower()
            if q_clean in existing_questions:
                logger.info(
                    f"oq_asm_merge_callback: Skipped duplicate Open Question: '{item.question}'"
                )
                continue

            start_idx = len(oqs) + 1
            oq_dict = {
                "id": f"OQ-{start_idx:03d}",
                "question": item.question,
                "severity": item.severity,
                "status": "open",
                "impact": item.impact,
                "answer": None,
                "assigned_to": item.assigned_to,
                "source_section": active_sec,
                "source_turn": current_turn,
            }
            oqs.append(oq_dict)
            existing_questions.add(q_clean)
            logger.info(
                f"oq_asm_merge_callback: Added new Open Question {oq_dict['id']}"
            )
        state["open_questions"] = oqs

    # Merge Assumptions (Max 3 new per turn)
    if parsed.assumptions:
        asms: list[dict[str, Any]] = list(state.get("assumptions", []))
        existing_statements = {
            str(asm.get("statement", "")).strip().lower() for asm in asms
        }
        for item in parsed.assumptions[:3]:
            stmt_clean = item.statement.strip().lower()
            if stmt_clean in existing_statements:
                logger.info(
                    f"oq_asm_merge_callback: Skipped duplicate Assumption: '{item.statement}'"
                )
                continue

            start_idx = len(asms) + 1
            asm_dict = {
                "id": f"ASM-{start_idx:02d}",
                "statement": item.statement,
                "source_section": active_sec,
                "source_turn": current_turn,
            }
            asms.append(asm_dict)
            existing_statements.add(stmt_clean)
            logger.info(f"oq_asm_merge_callback: Added new Assumption {asm_dict['id']}")
        state["assumptions"] = asms


async def oq_asm_inject_context_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> None:
    """Inject Feature Definition artifact data, Open Questions & Assumptions context into LLM request."""
    state = callback_context.state
    active_sec = state.get("active_section", "feature_definition")
    all_artifacts = state.get("artifacts", {})
    section_artifact = all_artifacts.get(active_sec, all_artifacts.get("feature_definition", {}))
    oqs = state.get("open_questions", [])
    asms = state.get("assumptions", [])

    context_parts = []

    current_data_str = json.dumps(section_artifact, ensure_ascii=False, indent=2)
    context_parts.append(
        f"=== CURRENT ARTIFACT DATA ({active_sec}) ===\n{current_data_str}"
    )

    if oqs:
        oqs_str = "\n".join(
            f"- [{oq.get('id', 'OQ')}] {oq.get('question', '')} (status: {oq.get('status', 'open')})"
            for oq in oqs
        )
        context_parts.append(f"=== EXISTING OPEN QUESTIONS ===\n{oqs_str}")

    if asms:
        asms_str = "\n".join(
            f"- [{asm.get('id', 'ASM')}] {asm.get('statement', '')}" for asm in asms
        )
        context_parts.append(f"=== EXISTING ASSUMPTIONS ===\n{asms_str}")

    if context_parts:
        context_text = "\n\n".join(context_parts)
        insert_context(llm_request, context_text)
        logger.info(
            f"oq_asm_inject_context_callback: [ARTIFACT STATE] section={active_sec} artifact={section_artifact} | "
            f"Injected OQ ({len(oqs)}) and ASM ({len(asms)}) context into llm_request"
        )
