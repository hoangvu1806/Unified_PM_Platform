"""Optional VA LLM helpers — commentary / discuss. Never decides PASS/FAIL."""

from __future__ import annotations

import copy
import json
import os
from typing import Any

from agents.sub_graph.shared.context_trim import (
    trim_business_rules,
    trim_feature_definition,
    trim_open_items,
    trim_workflow,
)
from config.llm_resolve import resolve_llm_endpoint
from utils import logging

logger = logging()

_MISSING = object()

READONLY_KEYS: tuple[str, ...] = (
    "artifacts",
    "flags",
    "sections_status",
    "feature_status",
    "open_questions",
    "assumptions",
    "last_validation",
    "package_exported",
    "_va_result",
    "_va_evidence",
    "_va_last_snapshot_hash",
    "_va_envelope",
    "_va_failed",
    "_va_warnings",
    "_va_passed_checks",
)

VA_SYSTEM_PROMPT = """Bạn là **Validation Agent (VA)** trên cùng session với BA Agent.

Nhiệm vụ của bạn:
1. Giải thích báo cáo validate (Python rules) một cách rõ ràng, thân thiện, chi tiết.
2. Gợi ý PO/BA **cách sửa phía BA chat** (FD / BR / WF / UC) khi có findings.
3. Đặt câu hỏi làm rõ khi báo cáo chưa đủ để PO hiểu bước tiếp theo.
4. Trả lời tự do về findings, coverage, wiki evidence — citing `check_id` và wiki `page_id`.

Ràng buộc cứng (không được phá):
- Bạn **không** phê duyệt / reject wiki. Approve wiki là việc của người.
- Bạn **không** sửa Business Rules, User Stories (use_cases), Feature Definition, Workflow, flags, hay section completion.
- Bạn **không** quyết định PASS/FAIL. Outcome `passed | passed_with_warnings | failed | blocked | no_change` do Python rules đặt; không được đảo status.
- Muốn đổi gói BA: hướng PO mở **BA chat** (nếu chat chưa freeze sau Export). Sau Export, BA chat đóng băng; VA discuss vẫn mở.
- Luôn cite `check_id` (ví dụ V-02, V-08, V-WIKI-01) và wiki `page_id` khi nói về findings / evidence.
- Artifact trong context chỉ để đọc. Không yêu cầu hệ thống ghi artifact.

Ngôn ngữ: theo User (thường tiếng Việt). Giọng điệu giống BA discussion: cụ thể, có checklist, không nói mã nội bộ trừ check_id / page_id.
"""

EXPLAIN_USER_PREFIX = (
    "Dưới đây là báo cáo validate do Python rules tạo. "
    "Hãy giải thích findings, gợi ý sửa ở BA chat, và hỏi làm rõ nếu cần. "
    "Không đảo PASS/FAIL. Không sửa artifact."
)


def va_llm_allowed() -> bool:
    """Skip live LLM during unit tests unless explicitly enabled."""
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("VA_LLM_IN_TESTS") != "1":
        return False
    return True


def maybe_llm_completion(
    system_prompt: str,
    user_prompt: str,
    *,
    timeout: float = 90.0,
) -> str | None:
    """Best-effort chat completion. Returns None on skip/timeout/error. Never raises."""
    if not va_llm_allowed():
        return None
    try:
        endpoint = resolve_llm_endpoint()
        api_key = (endpoint.api_key or "").strip()
        if not api_key:
            return None
        from openai import OpenAI

        client = OpenAI(
            base_url=endpoint.api_base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=endpoint.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=4096,
        )
        choice = (response.choices or [None])[0]
        if choice is None or choice.message is None:
            return None
        text = (choice.message.content or "").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"VA LLM completion skipped: {exc}")
        return None


def last_report(state: dict[str, Any]) -> dict[str, Any]:
    last = state.get("last_validation") or state.get("_va_result") or {}
    return last if isinstance(last, dict) else {}


def build_readonly_context(state: dict[str, Any]) -> str:
    """Read-only package + last VA report for LLM inject. Does not write state."""
    artifacts = dict(state.get("artifacts") or {})
    last = last_report(state)
    evidence = last.get("evidence_references") or state.get("_va_evidence") or []
    payload = {
        "feature_status": state.get("feature_status"),
        "package_exported": bool(state.get("package_exported")),
        "outcome": last.get("status"),
        "ruleset_version": last.get("ruleset_version"),
        "validated_at": last.get("validated_at"),
        "failed_checks": last.get("failed_checks") or [],
        "warnings": last.get("warnings") or [],
        "passed_checks": last.get("passed_checks") or [],
        "coverage_summary": last.get("coverage_summary") or {},
        "evidence_references": evidence,
        "deterministic_report": last.get("agent_response") or "",
        "feature_definition": trim_feature_definition(artifacts.get("feature_definition") or {}),
        "business_rules": trim_business_rules(artifacts.get("business_rules") or []),
        "workflow": trim_workflow(artifacts.get("workflow") or {}),
        "use_cases": (artifacts.get("use_cases") or [])[:12],
        "open_questions": trim_open_items(state.get("open_questions") or []),
        "assumptions": trim_open_items(state.get("assumptions") or []),
    }
    return (
        "=== VALIDATION CONTEXT (READ-ONLY) ===\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "=== RULES ===\n"
        "Outcome above is final. Do not change it. "
        "Cite check_id and wiki page_id. Point BA-side edits to BA chat."
    )


def capture_readonly_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    snap: dict[str, Any] = {}
    for key in READONLY_KEYS:
        value = state.get(key, _MISSING)
        if value is _MISSING:
            continue
        try:
            snap[key] = copy.deepcopy(value)
        except Exception:  # noqa: BLE001
            snap[key] = value
    return snap


def restore_readonly_snapshot(state: dict[str, Any], snap: dict[str, Any] | None) -> None:
    """Put artifacts/status back. VA discuss must not persist LLM side-effects."""
    if not snap:
        return
    for key, value in snap.items():
        state[key] = value
    if state.get("_va_readonly_snapshot", _MISSING) is not _MISSING:
        state["_va_readonly_snapshot"] = None


def attach_llm_commentary(state: dict[str, Any], commentary: str | None) -> str:
    """Store LLM text as appendix. Never changes outcome or feature_status."""
    text = (commentary or "").strip()
    if not text:
        return ""
    last = last_report(state)
    if not last:
        return text
    outcome = last.get("status")
    last["llm_commentary"] = text
    report = str(last.get("agent_response") or "")
    marker = "**Validation Agent (gợi ý):**"
    appendix = f"\n\n---\n{marker}\n{text}"
    if marker not in report:
        last["agent_response"] = report + appendix
    last["status"] = outcome
    state["last_validation"] = last
    result = state.get("_va_result")
    if isinstance(result, dict):
        result["llm_commentary"] = text
        result["agent_response"] = last.get("agent_response")
        result["status"] = outcome
        state["_va_result"] = result
    return text


def explain_validation_with_llm(state: dict[str, Any]) -> str:
    """Optional post-report commentary. Empty string if LLM is unavailable."""
    last = last_report(state)
    if not last:
        return ""
    try:
        user_prompt = f"{EXPLAIN_USER_PREFIX}\n\n{build_readonly_context(state)}"
        commentary = maybe_llm_completion(VA_SYSTEM_PROMPT, user_prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"VA explain LLM skipped: {exc}")
        return ""
    return attach_llm_commentary(state, commentary)
