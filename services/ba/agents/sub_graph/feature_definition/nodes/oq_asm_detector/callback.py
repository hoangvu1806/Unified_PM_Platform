"""Callbacks for OQ & ASM Detector Node."""

from __future__ import annotations

import json
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from agents.sub_graph.feature_definition.schemas import (
    OQASMDetectionData,
    OQFollowThroughData,
)
from callbacks.inject_context import insert_context
from utils import logging
from utils.utils import parse_str_to_dict

logger = logging()
OQ_SYNC_VERSION = 2

_OQ_ANSWER_RE = re.compile(
    r"(?:trả\s*lời|traloi|answer|resolve)?\s*(OQ-\d{3})\s*[:：\-–]\s*(.+)",
    re.IGNORECASE,
)


def _canonicalize_artifact_refs(refs: Any, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize references to singleton artifacts to their real state key."""
    artifacts = state.get("artifacts") or {}
    feature_definition = artifacts.get("feature_definition") or {}
    feature_definition_id = str(feature_definition.get("id") or "feature_definition")
    normalized: list[dict[str, Any]] = []
    for raw in refs or []:
        ref = raw.model_dump() if hasattr(raw, "model_dump") else raw
        if not isinstance(ref, dict):
            continue
        item = dict(ref)
        if str(item.get("artifact_type") or "").lower() == "feature_definition":
            # FD is a singleton artifact and often has no generated ID. The model
            # may invent a plausible ID (e.g. FD-AUTH-001), which cannot be applied.
            item["artifact_id"] = feature_definition_id
        normalized.append(item)
    return normalized


def _oq_domains(text: str) -> dict[str, tuple[str, ...]]:
    domains: dict[str, tuple[str, ...]] = {}
    if re.search(r"sso|microsoft|google|single sign|liên kết tài khoản|đồng bộ tài khoản", text, re.I):
        domains["sso"] = (r"sso", r"microsoft", r"google", r"single sign", r"liên kết tài khoản", r"đồng bộ tài khoản")
    if re.search(r"mật khẩu|password|đặt lại|reset", text, re.I):
        domains["password"] = (r"mật khẩu", r"password", r"đặt lại", r"reset")
    if re.search(r"otp|mã xác thực|gửi lại mã|khôi phục|recovery", text, re.I):
        domains["otp"] = (r"otp", r"mã xác thực", r"gửi lại mã", r"khôi phục", r"recovery")
    return domains


def _infer_oq_artifact_refs(question: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    """Find the existing BA artifacts an answered authentication OQ can affect."""
    text = " ".join(
        str(question.get(key) or "") for key in ("question", "answer", "impact")
    )
    domains = _oq_domains(text)
    if not domains:
        return []
    artifacts = state.get("artifacts") or {}
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(artifact_type: str, artifact_id: str, content: str) -> None:
        matched = []
        for domain, patterns in domains.items():
            candidates = list(patterns)
            if artifact_type == "ui_touchpoints":
                if domain == "sso":
                    candidates.extend((r"login", r"sign.?in", r"đăng nhập"))
                elif domain == "password":
                    candidates.extend((r"forgot", r"quên mật khẩu"))
                elif domain == "otp":
                    candidates.extend((r"forgot", r"quên mật khẩu", r"verification", r"xác thực"))
            if any(re.search(pattern, content, re.I) for pattern in candidates):
                matched.append(domain)
        key = (artifact_type, artifact_id.upper())
        if matched and key not in seen:
            refs.append({
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
                "reason": f"OQ impacts {', '.join(matched)} authentication rules/flow.",
            })
            seen.add(key)

    for item in artifacts.get("business_rules") or []:
        if isinstance(item, dict) and item.get("id"):
            add("business_rules", str(item["id"]), json.dumps(item, ensure_ascii=False))

    workflow = artifacts.get("workflow") or {}
    workflow_text = str(workflow.get("workflow_md_content") or "") if isinstance(workflow, dict) else str(workflow)
    heading = re.compile(
        r"(?im)^#{1,3}[^\n]*\b(WF-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+)\b[^\n]*(?:\n|$)"
    )
    headings = list(heading.finditer(workflow_text))
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(workflow_text)
        add("workflow", match.group(1).upper(), workflow_text[match.start():end])

    for item in artifacts.get("use_cases") or []:
        if isinstance(item, dict) and item.get("id"):
            add("use_cases", str(item["id"]), json.dumps(item, ensure_ascii=False))

    touchpoints = artifacts.get("ui_touchpoints") or []
    if isinstance(touchpoints, dict):
        touchpoints = touchpoints.get("ui_touchpoints") or touchpoints.get("items") or []
    for item in touchpoints:
        if isinstance(item, dict) and item.get("id"):
            add("ui_touchpoints", str(item["id"]), json.dumps(item, ensure_ascii=False))

    return refs


def _resolve_oq_artifact_refs(question: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    text = " ".join(str(question.get(key) or "") for key in ("question", "answer", "impact"))
    domains = _oq_domains(text)
    refs = _canonicalize_artifact_refs(question.get("affected_artifacts") or [], state)
    # Authentication-policy OQs belong in the related BR/Workflow/US artifacts,
    # not the Feature Definition singleton merely because a detector guessed an FD ID.
    if domains:
        refs = [ref for ref in refs if ref.get("artifact_type") != "feature_definition"]
    by_key = {
        (str(ref.get("artifact_type") or ""), str(ref.get("artifact_id") or "").upper()): ref
        for ref in refs
    }
    for ref in _infer_oq_artifact_refs(question, state):
        by_key[(ref["artifact_type"], ref["artifact_id"].upper())] = ref
    return list(by_key.values())


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
        if (
            target.get("status") == "resolved"
            and target.get("sync_status") == "verified"
            and str(target.get("answer") or "").strip() == answer
            and status == "resolved"
        ):
            continue
        target["status"] = status
        target["answer"] = answer
        if status == "resolved":
            target["sync_status"] = "pending"
            refs = _canonicalize_artifact_refs(raw.get("affected_artifacts") or [], state)
            if refs:
                target["affected_artifacts"] = [
                    ref.model_dump() if hasattr(ref, "model_dump") else ref
                    for ref in refs
                    if isinstance(ref, dict) or hasattr(ref, "model_dump")
                ]
            queue = {
                str(item.get("id") or "").upper(): item
                for item in (state.get("_oq_sync_queue") or [])
                if isinstance(item, dict)
            }
            queued = dict(queue.get(oq_id) or {})
            queued.update(
                {
                    "id": oq_id,
                    "answer": answer,
                    "question": target.get("question", ""),
                    "severity": target.get("severity", "warning"),
                    "affected_artifacts": target.get("affected_artifacts") or [],
                }
            )
            queue[oq_id] = queued
            state["_oq_sync_queue"] = list(queue.values())
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
    model_resolutions = list(parsed.resolved_questions or [])
    apply_oq_resolutions(state, model_resolutions)
    model_ids = {
        str(item.id if hasattr(item, "id") else item.get("id") or "").upper()
        for item in model_resolutions
    }
    fallback_resolutions = [
        item
        for item in resolutions_from_user_message(user_text_from_context(callback_context))
        if item["id"] not in model_ids
    ]
    apply_oq_resolutions(state, fallback_resolutions)

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
                "affected_artifacts": item.affected_artifacts or [],
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
    context_parts.append(
        "=== ALL CURRENT BA ARTIFACTS (use to identify exact OQ dependencies) ===\n"
        + json.dumps(all_artifacts, ensure_ascii=False, indent=2)
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


async def oq_followthrough_before(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    queue = ensure_oq_sync_queue(callback_context.state)
    current_id = str(callback_context.state.get("_oq_sync_current_id") or "").upper()
    if current_id:
        queue = [item for item in queue if str(item.get("id") or "").upper() == current_id]
    if not queue:
        from google.genai import types

        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=(
                            '{"reviewed_oq_ids":[],"impacted_artifacts":[],'
                            '"updates":[],"no_change_reason":"No pending OQ answers."}'
                        )
                    )
                ],
            )
        )
    state = callback_context.state
    all_artifacts = state.get("artifacts") or {}
    oq_by_id = {
        str(item.get("id") or "").upper(): item
        for item in (state.get("open_questions") or [])
    }
    selected: dict[str, Any] = {}
    resolutions: list[dict[str, Any]] = []
    requested: list[dict[str, str]] = []
    selected_refs: set[tuple[str, str]] = set()

    for item in queue:
        oq_id = str(item.get("id") or "").upper()
        question = oq_by_id.get(oq_id) or {}
        refs = _resolve_oq_artifact_refs(
            {**question, **item, "id": oq_id}, state
        )
        item["affected_artifacts"] = refs
        if question:
            question["affected_artifacts"] = refs
        normalized_refs: list[dict[str, str]] = []
        seen_for_oq: set[tuple[str, str]] = set()
        for ref in refs:
            if hasattr(ref, "model_dump"):
                ref = ref.model_dump()
            if not isinstance(ref, dict):
                continue
            artifact_type = str(ref.get("artifact_type") or "")
            artifact_id = str(ref.get("artifact_id") or "")
            key = (artifact_type, artifact_id.upper())
            if not artifact_type or not artifact_id or key in seen_for_oq:
                continue
            seen_for_oq.add(key)
            normalized = {
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
                "reason": str(ref.get("reason") or ""),
                "oq_id": oq_id,
            }
            normalized_refs.append(normalized)
            requested.append(normalized)
            if key in selected_refs:
                continue
            selected_refs.add(key)

            source = all_artifacts.get(artifact_type)
            if artifact_type == "feature_definition":
                source_id = str((source or {}).get("id") or "feature_definition")
                if artifact_id.lower() in {"feature_definition", source_id.lower()}:
                    selected[artifact_type] = source
            elif artifact_type == "workflow":
                workflow = source if isinstance(source, dict) else {}
                content = str(workflow.get("workflow_md_content") or "")
                heading = re.compile(
                    r"(?im)^#{1,3}[^\n]*\b(WF-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+)\b[^\n]*(?:\n|$)"
                )
                matches = list(heading.finditer(content))
                for index, match in enumerate(matches):
                    if match.group(1).upper() != artifact_id.upper():
                        continue
                    end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
                    current = selected.setdefault(
                        artifact_type, {"workflow_md_content": ""}
                    )
                    block = content[match.start():end].strip()
                    current["workflow_md_content"] = "\n\n".join(
                        part
                        for part in [current.get("workflow_md_content", ""), block]
                        if part
                    )
                    break
            elif isinstance(source, list):
                matches = [
                    entry for entry in source
                    if isinstance(entry, dict)
                    and str(entry.get("id") or "").upper() == artifact_id.upper()
                ]
                if matches:
                    selected.setdefault(artifact_type, []).extend(matches)

        resolutions.append(
            {
                **item,
                "id": oq_id,
                "affected_artifacts": normalized_refs,
                "question": question.get("question") or item.get("question") or "",
            }
        )

    context = {
        "pending_resolutions": resolutions,
        "open_questions": [oq_by_id[item["id"]] for item in resolutions if item["id"] in oq_by_id],
        "requested_artifacts": requested,
        "artifacts": selected,
    }
    insert_context(
        llm_request,
        "=== TARGETED OQ FOLLOW-THROUGH INPUT (ONLY REFERENCED ARTIFACTS) ===\n"
        + json.dumps(context, ensure_ascii=False, indent=2),
    )
    # Each model call gets exactly one answered OQ and its referenced artifacts.
    callback_context.state["_oq_sync_queue"] = queue[:1]
    callback_context.state["open_questions"] = list(oq_by_id.values())
    return None


def ensure_oq_sync_queue(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Recover retryable OQ answers if an earlier stream ended before queue cleanup."""
    questions = list(state.get("open_questions") or [])
    for question in questions:
        if question.get("affected_artifacts"):
            question["affected_artifacts"] = _canonicalize_artifact_refs(
                question.get("affected_artifacts"), state
            )
    state["open_questions"] = questions
    queue = list(state.get("_oq_sync_queue") or [])
    if queue:
        for item in queue:
            item["affected_artifacts"] = _canonicalize_artifact_refs(
                item.get("affected_artifacts") or [], state
            )
    queued_ids = {str(item.get("id") or "").upper() for item in queue}
    queue.extend([
        {
            "id": str(item.get("id") or "").upper(),
            "answer": item.get("answer") or "",
            "question": item.get("question") or "",
            "severity": item.get("severity") or "warning",
            "affected_artifacts": _canonicalize_artifact_refs(
                item.get("affected_artifacts") or [], state
            ),
        }
        for item in (state.get("open_questions") or [])
        if item.get("status") == "resolved"
        and item.get("sync_status") in {"pending", "failed"}
        and str(item.get("id") or "").upper() not in queued_ids
    ])
    # One-time migration: earlier builds could mark an OQ verified after syncing
    # the wrong artifact. Reconcile saved answers through the corrected targeting
    # and review pass the next time this section is used.
    if int(state.get("_oq_sync_version") or 0) < OQ_SYNC_VERSION:
        queue_ids = {str(item.get("id") or "").upper() for item in queue}
        for item in questions:
            oq_id = str(item.get("id") or "").upper()
            if (
                item.get("status") == "resolved"
                and item.get("answer")
                and oq_id
                and oq_id not in queue_ids
            ):
                item["sync_status"] = "pending"
                queue.append({
                    "id": oq_id,
                    "answer": item.get("answer") or "",
                    "question": item.get("question") or "",
                    "severity": item.get("severity") or "warning",
                    "affected_artifacts": item.get("affected_artifacts") or [],
                })
                queue_ids.add(oq_id)
    for item in queue:
        oq = next(
            (question for question in questions if str(question.get("id") or "").upper() == str(item.get("id") or "").upper()),
            None,
        )
        if oq:
            item["affected_artifacts"] = _resolve_oq_artifact_refs(oq, state)
            oq["affected_artifacts"] = item["affected_artifacts"]
    state["open_questions"] = questions
    if queue:
        state["_oq_sync_queue"] = queue
    else:
        state["_oq_sync_queue"] = []
    return queue


def _replace_workflow_block(content: str, workflow_id: str, replacement: str) -> str | None:
    heading = re.compile(
        r"(?im)^#{1,3}[^\n]*\b(WF-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+)\b[^\n]*(?:\n|$)"
    )
    matches = list(heading.finditer(content))
    target = workflow_id.upper()
    for index, match in enumerate(matches):
        if match.group(1).upper() != target:
            continue
        if not re.search(heading, replacement):
            return None
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        return content[: match.start()] + replacement.strip() + "\n\n" + content[end:].lstrip()
    return None


def _apply_oq_artifact_update(artifacts: dict[str, Any], update: Any) -> bool:
    try:
        value = json.loads(update.updated_value) if update.artifact_type != "workflow" else update.updated_value
    except (TypeError, json.JSONDecodeError):
        return False

    if update.artifact_type == "workflow":
        workflow = dict(artifacts.get("workflow") or {})
        old_content = str(workflow.get("workflow_md_content") or "")
        new_content = _replace_workflow_block(old_content, update.artifact_id, value)
        if new_content is None:
            return False
        if new_content == old_content:
            return True
        workflow["workflow_md_content"] = new_content
        artifacts["workflow"] = workflow
        return True

    if update.artifact_type == "feature_definition":
        current = artifacts.get("feature_definition") or {}
        if not isinstance(value, dict) or update.artifact_id not in {
            "feature_definition",
            str(current.get("id") or ""),
        }:
            return False
        allowed = {"goal", "actors", "scope_in", "scope_out"}
        if not set(value).issubset(allowed):
            return False
        merged = dict(current)
        merged.update(value)
        if merged == current:
            return True
        artifacts["feature_definition"] = merged
        return True

    collection = artifacts.get(update.artifact_type)
    if not isinstance(collection, list) or not isinstance(value, dict):
        return False
    if str(value.get("id") or "").upper() != update.artifact_id.upper():
        return False
    for index, item in enumerate(collection):
        if isinstance(item, dict) and str(item.get("id") or "").upper() == update.artifact_id.upper():
            if item == value:
                return True
            collection[index] = value
            artifacts[update.artifact_type] = collection
            return True
    return False


async def oq_followthrough_merge(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> None:
    state = callback_context.state
    queue = state.get("_oq_sync_queue") or []
    if not queue or not llm_response.content or not llm_response.content.parts:
        return
    current_turn = state.get("current_turn")
    prior_result = state.get("_oq_sync_result") or {}
    if prior_result.get("turn") != current_turn:
        prior_result = {}
    parsed_dict = parse_str_to_dict(llm_response.content.parts[0].text or "")
    try:
        result = OQFollowThroughData.model_validate(parsed_dict or {})
    except Exception as exc:  # noqa: BLE001
        current_id = str(state.get("_oq_sync_current_id") or "").upper()
        oqs = list(state.get("open_questions") or [])
        for question in oqs:
            if str(question.get("id") or "").upper() == current_id:
                question["sync_status"] = "failed"
        prior_errors = list(prior_result.get("errors") or [])
        detail = f"Could not parse OQ sync result for {current_id or 'current question'}: {exc}"
        if detail not in prior_errors:
            prior_errors.append(detail)
        pending_ids = [
            str(item.get("id") or "").upper()
            for item in oqs
            if item.get("status") == "resolved"
            and item.get("sync_status") in {"pending", "failed"}
        ]
        state["open_questions"] = oqs
        state["_oq_sync_result"] = {
            "turn": state.get("current_turn"),
            "errors": prior_errors,
            "updated_artifacts": list(prior_result.get("updated_artifacts") or []),
            "pending_oq_ids": pending_ids,
            "review": prior_result.get("review") or state.get("_ba_change_review") or {},
        }
        state["_oq_sync_queue"] = ensure_oq_sync_queue(state)
        return

    artifacts = dict(state.get("artifacts") or {})
    update_results: dict[tuple[str, str, str], bool] = {}
    updated_artifacts: list[str] = []
    changed_types: set[str] = set()
    synced_types: set[str] = set()
    errors: list[str] = []
    for update in result.updates:
        key = (update.oq_id.upper(), update.artifact_type, update.artifact_id.upper())
        before = json.dumps(artifacts.get(update.artifact_type), ensure_ascii=False, sort_keys=True)
        applied = _apply_oq_artifact_update(artifacts, update)
        after = json.dumps(artifacts.get(update.artifact_type), ensure_ascii=False, sort_keys=True)
        update_results[key] = applied
        if applied:
            synced_types.add(update.artifact_type)
            if before != after:
                label = f"{update.artifact_type}:{update.artifact_id}"
                if label not in updated_artifacts:
                    updated_artifacts.append(label)
                changed_types.add(update.artifact_type)
        else:
            errors.append(f"Không áp dụng được cập nhật {update.artifact_type}:{update.artifact_id}.")

    state["artifacts"] = artifacts
    oqs = list(state.get("open_questions") or [])
    queue_by_id = {str(item.get("id") or "").upper(): item for item in queue}
    refs_by_oq: dict[str, list[Any]] = {}
    for ref in result.impacted_artifacts:
        if ref.oq_id:
            refs_by_oq.setdefault(ref.oq_id.upper(), []).append(ref)
    updates_by_oq: dict[str, list[Any]] = {}
    for update in result.updates:
        updates_by_oq.setdefault(update.oq_id.upper(), []).append(update)

    pending_ids: list[str] = []
    for oq in oqs:
        oq_id = str(oq.get("id") or "").upper()
        if oq_id not in queue_by_id:
            continue
        queued_refs = queue_by_id[oq_id].get("affected_artifacts") or []
        refs = list(queued_refs) + list(refs_by_oq.get(oq_id, []))
        unique_refs: list[Any] = []
        seen_refs: set[tuple[str, str]] = set()
        for ref in refs:
            ref_type = ref.get("artifact_type") if isinstance(ref, dict) else ref.artifact_type
            ref_id = ref.get("artifact_id") if isinstance(ref, dict) else ref.artifact_id
            key = (str(ref_type), str(ref_id).upper())
            if key not in seen_refs:
                unique_refs.append(ref)
                seen_refs.add(key)
        refs = unique_refs
        updates = updates_by_oq.get(oq_id, [])
        for update in updates:
            key = (update.artifact_type, update.artifact_id.upper())
            if key not in seen_refs:
                refs.append(update)
                seen_refs.add(key)
        has_updates_for_oq = bool(updates)
        explicitly_reviewed_no_change = (
            oq_id in {str(item).upper() for item in result.reviewed_oq_ids}
            and bool(result.no_change_reason)
            and not has_updates_for_oq
        )
        if explicitly_reviewed_no_change:
            complete = True
        elif refs:
            complete = all(
                update_results.get(
                    (
                        oq_id,
                        str(ref.get("artifact_type") if isinstance(ref, dict) else ref.artifact_type),
                        str(ref.get("artifact_id") if isinstance(ref, dict) else ref.artifact_id).upper(),
                    ),
                    False,
                )
                for ref in refs
            )
        else:
            complete = oq_id in {item.upper() for item in result.reviewed_oq_ids} and bool(
                result.no_change_reason
            ) and not updates
        if complete:
            oq["status"] = "resolved"
            oq["sync_status"] = "verified"
            oq["affected_artifacts"] = [
                ref.model_dump() if hasattr(ref, "model_dump") else ref for ref in refs
            ]
        else:
            oq["status"] = "resolved"
            oq["sync_status"] = "pending"
            pending_ids.append(oq_id)
            for ref in refs:
                ref_type = ref.get("artifact_type") if isinstance(ref, dict) else ref.artifact_type
                ref_id = ref.get("artifact_id") if isinstance(ref, dict) else ref.artifact_id
                if not update_results.get((oq_id, str(ref_type), str(ref_id).upper()), False):
                    detail = f"{oq_id}: chưa đồng bộ {ref_type}:{ref_id}."
                    if detail not in errors:
                        errors.append(detail)
            if not refs and not result.no_change_reason:
                errors.append(f"{oq_id}: agent chưa xác định artifact cần đồng bộ hoặc xác nhận không cần sửa.")
    state["open_questions"] = oqs

    from agents.ba_agent.section_gate import (
        mark_downstream_needs_review,
        record_package_change_review,
    )
    from agents.ba_agent.constants import (
        SECTION_BUSINESS_RULES,
        SECTION_USE_CASES,
        SECTION_WORKFLOW,
    )

    section_for_type = {
        "feature_definition": "feature_definition",
        "business_rules": SECTION_BUSINESS_RULES,
        "workflow": SECTION_WORKFLOW,
        "use_cases": SECTION_USE_CASES,
        "ui_touchpoints": "ui_touchpoints",
    }
    for artifact_type in changed_types:
        mark_downstream_needs_review(state, section_for_type[artifact_type])
    sections = dict(state.get("sections_status") or {})
    for artifact_type in synced_types:
        section_id = section_for_type.get(artifact_type)
        if section_id and sections.get(section_id) == "needs_review":
            sections[section_id] = "completed"
    state["sections_status"] = sections
    if "ui_touchpoints" in synced_types:
        sections["ui_touchpoints"] = "completed"
        state["sections_status"] = sections
    if (state.get("sections_status") or {}).get("bpmn_reference") == "needs_review":
        from managers.control.bpmn import ensure_bpmn_artifact

        ensure_bpmn_artifact(state, force=True)
    record_package_change_review(state, "open_questions")

    processed_ids = list(state.get("_oq_sync_processed_ids") or [])
    current_id = str(state.get("_oq_sync_current_id") or "").upper()
    if current_id and current_id not in processed_ids:
        processed_ids.append(current_id)
    state["_oq_sync_processed_ids"] = processed_ids

    all_pending_ids = [
        str(item.get("id") or "").upper()
        for item in oqs
        if item.get("status") == "resolved"
        and item.get("sync_status") in {"pending", "failed"}
    ]
    all_updated = list(dict.fromkeys(
        [*(prior_result.get("updated_artifacts") or []), *updated_artifacts]
    ))
    all_errors = list(dict.fromkeys(
        [*(prior_result.get("errors") or []), *errors]
    ))
    state["_oq_sync_result"] = {
        "turn": current_turn,
        "updated_artifacts": all_updated,
        "pending_oq_ids": all_pending_ids,
        "errors": all_errors,
        "review": state.get("_ba_change_review") or {},
    }
    state["_oq_sync_queue"] = ensure_oq_sync_queue(state)
    if not all_pending_ids:
        state["_oq_sync_version"] = OQ_SYNC_VERSION
