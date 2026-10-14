"""Validation Agent logic (testable without ADK nodes)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from datetime import datetime, timezone

from agents.ba_agent.status import apply_validation_result
from agents.sub_graph.validation_agent.checks import (
    RULESET_VERSION,
    coverage_summary,
    run_cross_section_checks,
)
from agents.sub_graph.validation_agent.wiki_checks import run_firm_wiki_checks
from factory_wiki.store import WikiStore
from managers.control.envelope import (
    AGENT_VA,
    ARTIFACT_VA_REPORT,
    CONTRACT_VA_REPORT,
    common_envelope,
)
from managers.control.session import resolve_project_id


_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "một",
        "các",
        "và",
        "của",
        "cho",
        "với",
        "trên",
        "trong",
        "được",
        "không",
        "là",
        "có",
        "khi",
        "thì",
    }
)


def payload_from_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticket_type": state.get("ticket_type", "NEW_FEATURE"),
        "project_id": resolve_project_id(state),
        "artifacts": state.get("artifacts", {}),
        "sections_status": state.get("sections_status", {}),
        "open_questions": state.get("open_questions", []),
        "assumptions": state.get("assumptions", []),
        "flags": state.get("flags", {}),
    }


def wiki_queries_from_artifacts(artifacts: dict[str, Any], extra: dict[str, Any] | None = None) -> list[str]:
    """Build search queries from the live package — no hardcoded fixture terms."""
    extra = extra or {}
    texts: list[str] = []
    fd = artifacts.get("feature_definition") or {}
    for key in ("goal", "feature_title", "title"):
        value = extra.get(key) or fd.get(key)
        if value:
            texts.append(str(value))
    if extra.get("feature_title"):
        texts.append(str(extra["feature_title"]))
    for actor in fd.get("actors") or []:
        raw = str(actor)
        texts.append(raw.split(":", 1)[-1].strip() if ":" in raw else raw)
    for item in fd.get("scope_in") or []:
        texts.append(str(item))
    for rule in artifacts.get("business_rules") or []:
        if isinstance(rule, dict):
            texts.append(str(rule.get("statement") or ""))
        else:
            texts.append(str(rule))
    queries: list[str] = []
    seen: set[str] = set()
    for text in texts:
        cleaned = " ".join(str(text).split())
        if len(cleaned) >= 4:
            key = cleaned.lower()
            if key not in seen:
                seen.add(key)
                queries.append(cleaned[:80])
        for token in re.findall(r"[A-Za-zÀ-ỹ0-9]{4,}", cleaned):
            low = token.lower()
            if low in _STOPWORDS or low in seen:
                continue
            seen.add(low)
            queries.append(token)
    return queries[:12]


def run_schema_check(state: dict[str, Any]) -> dict[str, Any] | None:
    payload = payload_from_state(state)
    fd = payload["artifacts"].get("feature_definition", {})
    if not fd or not str(fd.get("goal", "")).strip():
        return {
            "status": "blocked",
            "agent_response": "📋 **Validation blocked**: Feature Definition thiếu goal — package chưa usable.",
            "failed_checks": [
                {
                    "check_id": "V-SCHEMA-01",
                    "name": "FD required",
                    "severity": "error",
                    "detail": "goal is empty",
                    "affected_sections": ["feature_definition"],
                }
            ],
            "warnings": [],
            "evidence_references": [],
        }
    state["_va_payload"] = payload
    return None


def wiki_approved_fingerprint(store: WikiStore, project_id: str) -> list[tuple[str, str, str, str]]:
    """Stable approved-page stamp so wiki updates invalidate the VA snapshot."""
    hits = store.list_approved(project_id=project_id, agent_name="validation-agent")
    return sorted(
        (
            str(hit.get("page_id") or ""),
            str(hit.get("version") or ""),
            str(hit.get("title") or ""),
            str(hit.get("updated_at") or ""),
        )
        for hit in hits
    )


def run_snapshot_check(
    state: dict[str, Any],
    store: WikiStore | None = None,
) -> dict[str, Any] | None:
    payload = state.get("_va_payload", {})
    project_id = str(
        state.get("project_id")
        or payload.get("project_id")
        or resolve_project_id(state)
    )
    wiki_fp = wiki_approved_fingerprint(store, project_id) if store is not None else []
    digest = hashlib.sha256(
        json.dumps(
            {"artifacts": payload.get("artifacts", {}), "wiki": wiki_fp},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    prev = state.get("_va_last_snapshot_hash")
    if prev and prev == digest:
        return {
            "status": "no_change",
            "agent_response": (
                f"📋 Chưa có thay đổi từ lần validate trước. "
                f"Tình trạng: **{state.get('feature_status', 'UNKNOWN')}**."
            ),
            "failed_checks": [],
            "warnings": [],
            "passed_checks": [],
            "evidence_references": list(state.get("_va_evidence") or []),
            "change_detected": False,
            "validated_at": None,
            "ruleset_version": RULESET_VERSION,
        }
    state["_va_current_digest"] = digest
    return None


def run_package_checks(state: dict[str, Any]) -> tuple[list[dict], list[dict], list[dict]]:
    """G1 BA-package checks. Penpot/UI-standard rules stay out of this slice."""
    return run_cross_section_checks(state)


def run_wiki_pull(
    state: dict[str, Any], store: WikiStore
) -> tuple[list[dict], list[dict], list[dict]]:
    """Pull approved wiki (full bodies) and run firm V-WIKI checks.

    Returns (evidence, failed_errors, wiki_warnings).
    Errors block Export; V-WIKI-05 warnings do not.
    """
    payload = state.get("_va_payload", {})
    project_id = str(
        state.get("project_id")
        or payload.get("project_id")
        or resolve_project_id(state)
    )
    artifacts = payload.get("artifacts", {})
    evidence: list[dict] = []
    failed = list(state.get("_va_failed", []))
    warnings: list[dict] = []
    seen: set[str] = set()

    queries = wiki_queries_from_artifacts(
        artifacts,
        {
            "feature_title": state.get("feature_title"),
            "title": state.get("feature_title"),
        },
    )
    hits: list[dict] = []
    # Live approved set (newest first) — not the first 5 rowids / fixture terms.
    hits.extend(store.list_approved(project_id=project_id))
    for query in queries:
        hits.extend(store.search(query, project_id=project_id, limit=50))

    pages: list[dict] = []
    for hit in hits:
        page_id = hit.get("page_id")
        if not page_id or page_id in seen:
            continue
        seen.add(page_id)
        evidence.append(
            {
                "page_id": page_id,
                "title": hit.get("title"),
                "snippet": hit.get("snippet"),
                "version": hit.get("version"),
            }
        )
        page = store.fetch(page_id, project_id=project_id)
        if page:
            pages.append(page)

    wiki_failed, wiki_warnings = run_firm_wiki_checks(pages=pages, artifacts=artifacts)
    failed.extend(wiki_failed)
    warnings.extend(wiki_warnings)
    return evidence, failed, warnings


def _attach_envelope(state: dict[str, Any], result: dict[str, Any]) -> None:
    session_id = str(state.get("session_id") or state.get("feature_id") or "")
    state["_va_envelope"] = common_envelope(
        correlation_id=session_id,
        project_id=resolve_project_id(state, session_id=session_id or None),
        feature_id=session_id,
        agent_id=AGENT_VA,
        contract_name=CONTRACT_VA_REPORT,
        artifact_type=ARTIFACT_VA_REPORT,
        artifact_status="proposed",
        payload={
            "outcome": result.get("status"),
            "findings": result.get("failed_checks") or [],
            "warnings": result.get("warnings") or [],
            "passed_checks": result.get("passed_checks") or [],
            "coverage_summary": result.get("coverage_summary") or {},
            "evidence_references": result.get("evidence_references") or [],
            "ruleset_version": result.get("ruleset_version") or RULESET_VERSION,
            "change_detected": result.get("change_detected"),
            "validated_at": result.get("validated_at"),
            "required_actions": [
                item.get("suggestion") or item.get("detail")
                for item in (result.get("failed_checks") or [])
                if item.get("detail") or item.get("suggestion")
            ],
        },
        input_references=[
            {"type": "wiki_page", "page_id": item.get("page_id")}
            for item in (result.get("evidence_references") or [])
            if item.get("page_id")
        ],
        validation={
            "schema_valid": True,
            "errors": [],
            "outcome": result.get("status"),
        },
    )


def build_validation_report(
    state: dict[str, Any],
    failed: list[dict],
    warnings: list[dict],
    evidence: list[dict],
    passed_checks: list[dict] | None = None,
) -> dict[str, Any]:
    passed_checks = passed_checks or []
    title = str(state.get("feature_title") or "this feature")
    now = datetime.now(timezone.utc).isoformat()
    artifacts = (state.get("_va_payload") or {}).get("artifacts") or state.get("artifacts") or {}
    coverage = coverage_summary(artifacts, len(evidence))
    if failed:
        lines = [f"📋 **Validation FAILED** — {title}\n"]
        for f in failed:
            page_bit = ""
            if f.get("evidence_page_id") or f.get("page_id"):
                page_bit = f" [{f.get('evidence_page_id') or f.get('page_id')}]"
            lines.append(f"- **{f.get('check_id') or ''} {f['name']}**{page_bit}: {f['detail']}")
            if f.get("suggestion"):
                lines.append(f"  Gợi ý: {f['suggestion']}")
        if warnings:
            lines.append("\n**Warnings:**")
            for w in warnings:
                lines.append(f"- {w['name']}: {w['detail']}")
        lines.append(
            "\nWiki findings: sửa **wiki** (hoặc package) rồi **re-Validate**. "
            "BA chat có thể ACK check_id nhưng không overwrite wiki."
        )
        status = "failed"
    else:
        status = "passed" if not warnings else "passed_with_warnings"
        headline = "PASSED" if status == "passed" else "PASSED WITH WARNINGS"
        lines = [f"📋 **Validation {headline}** — {title}"]
        if passed_checks:
            lines.append(
                "\n**Passed checks:** "
                + ", ".join(item.get("check_id") or item.get("name") or "" for item in passed_checks)
            )
        if warnings:
            lines.append("\n**Warnings (optional — không chặn export):**")
            for w in warnings:
                lines.append(f"- {w['name']}: {w['detail']}")
        if evidence:
            lines.append("\n**Wiki evidence (current approved):**")
            shown = evidence[:12]
            for e in shown:
                lines.append(f"- {e['page_id']}: {e['title']}")
            extra = len(evidence) - len(shown)
            if extra > 0:
                lines.append(f"- … +{extra} more approved pages")
        else:
            lines.append("\n**Wiki evidence:** không có trang approved (draft ẩn với VA).")
        lines.append(
            f"\nCoverage: {coverage['use_cases']} UC · {coverage['business_rules']} BR · "
            f"{coverage['exception_flows']} exception · {coverage['wiki_pages']} wiki pages."
        )
        lines.append("VA **không sửa** artifact BA. Muốn đổi gói hãy mở BA chat (nếu chưa freeze).")
    result = {
        "status": status,
        "agent_response": "\n".join(lines),
        "failed_checks": failed,
        "warnings": warnings,
        "passed_checks": passed_checks,
        "coverage_summary": coverage,
        "evidence_references": evidence,
        "change_detected": True,
        "validated_at": now,
        "ruleset_version": RULESET_VERSION,
    }
    state["_va_last_snapshot_hash"] = state.get("_va_current_digest")
    apply_validation_result(state, result)
    _attach_envelope(state, result)
    return result


def run_validation(state: dict[str, Any], store: WikiStore) -> str:
    blocked = run_schema_check(state)
    if blocked:
        state["_va_result"] = blocked
        apply_validation_result(state, blocked)
        _attach_envelope(state, blocked)
        return blocked["agent_response"]

    unchanged = run_snapshot_check(state, store)
    if unchanged:
        state["_va_result"] = unchanged
        _attach_envelope(state, unchanged)
        return unchanged["agent_response"]

    failed, warnings, passed_checks = run_package_checks(state)
    state["_va_failed"] = failed
    state["_va_warnings"] = warnings
    state["_va_passed_checks"] = passed_checks

    evidence, failed, wiki_warnings = run_wiki_pull(state, store)
    state["_va_evidence"] = evidence
    state["_va_failed"] = failed
    warnings = list(warnings) + list(wiki_warnings)
    state["_va_warnings"] = warnings

    result = build_validation_report(state, failed, warnings, evidence, passed_checks)
    state["_va_result"] = result
    return result["agent_response"]


def validation_not_ready_message(state: dict[str, Any]) -> str:
    """Explain why VA cannot run yet — does not mutate artifacts or status."""
    from agents.ba_agent.section_gate import (
        TIER1_SECTIONS,
        has_critical_open_oq,
        section_is_complete,
    )

    status = str(state.get("feature_status") or "DRAFT")
    lines = [
        "📋 **Validate Agent chưa chạy được.**",
        "",
        "Validate **không bỏ qua** cổng tuần tự FD → BR → WF → UC. "
        "Package phải đủ 4 section bắt buộc và không còn Open Question mức **critical**.",
        "",
        f"- `feature_status` hiện tại: **{status}**",
    ]
    for sec in TIER1_SECTIONS:
        done = "completed" if section_is_complete(state, sec) else "incomplete"
        lines.append(f"- `{sec}`: {done}")
    if has_critical_open_oq(state):
        lines.append("")
        lines.append("**Open questions critical còn mở** (trả lời trong BA chat bằng `OQ-00N:`):")
        for oq in state.get("open_questions") or []:
            if oq.get("status", "open") == "open" and oq.get("severity") == "critical":
                oid = oq.get("id") or "OQ"
                q = oq.get("question") or ""
                lines.append(f"- `{oid}`: {q}")
    lines.append("")
    lines.append(
        "Hãy hoàn tất BA chat trước, rồi bấm Validate (hoặc mở lại trang Validate Agent)."
    )
    return "\n".join(lines)


def discuss_validation_with_llm(state: dict[str, Any], user_message: str) -> str:
    """LLM discuss with keyword fallback. Never mutates artifacts/status."""
    from agents.sub_graph.validation_agent.llm import (
        VA_SYSTEM_PROMPT,
        build_readonly_context,
        capture_readonly_snapshot,
        maybe_llm_completion,
        restore_readonly_snapshot,
    )

    snap = capture_readonly_snapshot(state)
    try:
        user_prompt = (
            f"User: {user_message or ''}\n\n{build_readonly_context(state)}"
        )
        try:
            text = maybe_llm_completion(VA_SYSTEM_PROMPT, user_prompt)
        except Exception:  # noqa: BLE001
            text = None
        if text:
            return text
        return discuss_validation(state, user_message)
    finally:
        restore_readonly_snapshot(state, snap)


def discuss_validation(state: dict[str, Any], user_message: str) -> str:
    """Answer questions about the last VA report. Does not mutate BA artifacts."""
    last = state.get("last_validation") or state.get("_va_result") or {}
    if not last:
        from agents.ba_agent.section_gate import can_proceed_to_validation

        if not can_proceed_to_validation(state):
            return validation_not_ready_message(state)
    artifacts = dict(state.get("artifacts") or {})
    # Read-only snapshot — never write back.
    _ = artifacts
    if not last:
        return (
            "Chưa có lần Validate nào trên session này. "
            "Bấm **Run Validate** khi package đã PENDING_VALIDATION "
            "(FD → BR → WF → UC hoàn tất, không còn OQ critical)."
        )

    text = (user_message or "").lower()
    evidence = last.get("evidence_references") or state.get("_va_evidence") or []
    failed = last.get("failed_checks") or []
    warnings = last.get("warnings") or []
    report = last.get("agent_response") or ""

    if any(key in text for key in ("wiki", "evidence", "tài liệu", "document")):
        if not evidence:
            return "Không có wiki evidence (chỉ trang **approved** trong project mới được kéo)."
        lines = ["**Wiki evidence (approved only):**"]
        for item in evidence:
            pid = item.get("page_id") or ""
            title = item.get("title") or ""
            lines.append(f"- `{pid}`: {title}")
        return "\n".join(lines)

    if any(key in text for key in ("fail", "lỗi", "finding", "check")):
        if not failed:
            return "Không có failed_checks. Outcome: " + str(last.get("status") or "unknown")
        lines = ["**Findings:**"]
        for item in failed:
            line = f"- **{item.get('name')}**: {item.get('detail')}"
            if item.get("suggestion"):
                line += f" — {item['suggestion']}"
            lines.append(line)
        return "\n".join(lines)

    if "warning" in text:
        if not warnings:
            return "Không có warning."
        lines = ["**Warnings:**"]
        for item in warnings:
            lines.append(f"- {item.get('name')}: {item.get('detail')}")
        return "\n".join(lines)

    if any(key in text for key in ("coverage", "bao phủ", "passed check", "ruleset")):
        cov = last.get("coverage_summary") or {}
        passed = last.get("passed_checks") or []
        lines = [
            f"Outcome: **{last.get('status')}** · ruleset `{last.get('ruleset_version') or RULESET_VERSION}`",
            f"Coverage: {cov.get('use_cases', 0)} UC · {cov.get('business_rules', 0)} BR · "
            f"{cov.get('exception_flows', 0)} exception · {cov.get('wiki_pages', 0)} wiki.",
        ]
        if passed:
            lines.append("Passed: " + ", ".join(
                str(item.get("check_id") or item.get("name")) for item in passed
            ))
        return "\n".join(lines)

    chunks = [report or f"Outcome: **{last.get('status')}**"]
    if warnings and "warning" in text:
        chunks.append("\n**Warnings:**")
        for item in warnings:
            chunks.append(f"- {item.get('name')}: {item.get('detail')}")
    if evidence:
        chunks.append("\n**Wiki evidence:**")
        for item in evidence[:8]:
            chunks.append(f"- `{item.get('page_id')}`: {item.get('title')}")
    chunks.append(
        "\nVA **không sửa** artifact BA. Muốn đổi FD/BR/WF/UC hãy quay lại BA chat."
    )
    return "\n".join(chunks)


def run_va_turn(
    state: dict[str, Any],
    store: WikiStore,
    user_message: str = "",
    *,
    with_llm: bool = True,
) -> str:
    """Single VA subgraph entry: gated validate, or discuss last report.

    ``with_llm``: graph validate path is False (explain node runs next).
    Plain HTTP / tests may set True; LLM failure never changes rules outcome.
    """
    from agents.ba_agent.section_gate import can_proceed_to_validation

    wants_validate = bool(state.get("_va_run_validate")) or str(
        user_message or ""
    ).strip().startswith("[VALIDATE]")
    if "_va_run_validate" in state:
        state["_va_run_validate"] = False
    if wants_validate:
        if not can_proceed_to_validation(state):
            return validation_not_ready_message(state)
        before = dict(state.get("artifacts") or {})
        report = run_validation(state, store)
        # Safety: VA must not mutate BA artifacts even if a check is buggy.
        state["artifacts"] = before
        if with_llm:
            try:
                from agents.sub_graph.validation_agent.llm import explain_validation_with_llm

                extra = explain_validation_with_llm(state)
            except Exception:  # noqa: BLE001
                extra = ""
            if extra:
                return f"{report}\n\n---\n**Validation Agent (gợi ý):**\n{extra}"
        return report
    return discuss_validation_with_llm(state, user_message)
