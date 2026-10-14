"""BA-package cross-section checks for Validation Agent (G1, no Penpot)."""

from __future__ import annotations

import re
from typing import Any

RULESET_VERSION = "ba-va-1.1.0"

_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "hệ",
        "thống",
        "một",
        "các",
        "và",
        "của",
        "cho",
        "khi",
        "thì",
        "là",
        "có",
        "được",
        "không",
        "tôi",
        "muốn",
        "given",
        "when",
        "then",
    }
)


def _fd(artifacts: dict[str, Any]) -> dict[str, Any]:
    fd = artifacts.get("feature_definition") or {}
    return fd if isinstance(fd, dict) else {}


def _rules(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    raw = artifacts.get("business_rules") or []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
        elif item:
            out.append({"id": "", "statement": str(item)})
    return out


def _workflow_md(artifacts: dict[str, Any]) -> str:
    wf = artifacts.get("workflow") or {}
    if isinstance(wf, dict):
        return str(wf.get("workflow_md_content") or "")
    return str(wf or "")


def _use_cases(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    raw = artifacts.get("use_cases") or []
    return [item for item in raw if isinstance(item, dict)]


def _touchpoints(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    raw = artifacts.get("ui_touchpoints") or []
    if isinstance(raw, dict):
        raw = raw.get("ui_touchpoints") or []
    return [item for item in raw if isinstance(item, dict)]


def _actor_ids(fd: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for actor in fd.get("actors") or []:
        raw = str(actor).strip()
        aid = raw.split(":", 1)[0].strip() if ":" in raw else raw
        if aid:
            ids.append(aid)
    return ids


def _finding(
    check_id: str,
    name: str,
    detail: str,
    sections: list[str],
    *,
    severity: str = "error",
    suggestion: str = "",
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "name": name,
        "severity": severity,
        "detail": detail,
        "suggestion": suggestion,
        "affected_sections": sections,
    }


def _tokens(text: str) -> set[str]:
    return {
        tok.lower()
        for tok in re.findall(r"[A-Za-zÀ-ỹ0-9]{4,}", text or "")
        if tok.lower() not in _STOP
    }


def coverage_summary(artifacts: dict[str, Any], evidence_count: int) -> dict[str, Any]:
    wf = _workflow_md(artifacts)
    exceptions = re.findall(r"E-\d+", wf, flags=re.I)
    bpmn = artifacts.get("bpmn_reference") or {}
    bpmn_ok = bool(isinstance(bpmn, dict) and bpmn.get("bpmn_xml_content"))
    return {
        "use_cases": len(_use_cases(artifacts)),
        "business_rules": len(_rules(artifacts)),
        "fd_actors": len(_actor_ids(_fd(artifacts))),
        "exception_flows": len(exceptions),
        "ui_touchpoints": len(_touchpoints(artifacts)),
        "bpmn_present": bpmn_ok,
        "wiki_pages": evidence_count,
        "ruleset_version": RULESET_VERSION,
    }


def run_cross_section_checks(state: dict[str, Any]) -> tuple[list[dict], list[dict], list[dict]]:
    """Return failed, warnings, passed_checks."""
    payload = state.get("_va_payload") or {}
    artifacts = payload.get("artifacts") or state.get("artifacts") or {}
    fd = _fd(artifacts)
    rules = _rules(artifacts)
    wf_text = _workflow_md(artifacts)
    ucs = _use_cases(artifacts)
    actor_ids = _actor_ids(fd)
    actor_set = set(actor_ids)
    rule_ids = {str(rule.get("id") or "") for rule in rules if rule.get("id")}
    failed: list[dict] = []
    warnings: list[dict] = []
    passed: list[dict] = []

    if wf_text.strip() and rule_ids:
        missing = [rid for rid in sorted(rule_ids) if rid not in wf_text]
        if missing:
            failed.append(
                _finding(
                    "V-02",
                    "BR-WF traceability",
                    "BR " + ", ".join(missing) + " không xuất hiện trong workflow",
                    ["business_rules", "workflow"],
                    suggestion="Thêm bước hoặc BR Ref trong workflow, hoặc bỏ rule không còn dùng.",
                )
            )
        else:
            passed.append({"check_id": "V-02", "name": "BR-WF traceability"})

    for uc in ucs:
        actor = str(uc.get("actor_id") or "").strip()
        if actor and actor not in actor_set:
            failed.append(
                _finding(
                    "V-03",
                    "UC actor validity",
                    f"UC {uc.get('id')} actor {actor} không có trong FD",
                    ["use_cases", "feature_definition"],
                    suggestion="Thêm actor vào Feature Definition hoặc sửa actor_id của UC.",
                )
            )
    if ucs and actor_ids and all(
        str(uc.get("actor_id") or "").strip() in actor_set or not uc.get("actor_id")
        for uc in ucs
    ):
        passed.append({"check_id": "V-03", "name": "UC actor validity"})

    if wf_text.strip() and ucs:
        wf_l = wf_text.lower()
        for uc in ucs:
            for ac in uc.get("acceptance_criteria") or []:
                then = str((ac or {}).get("then") or "")
                tokens = _tokens(then)
                if len(tokens) < 2:
                    continue
                if not any(tok in wf_l for tok in tokens):
                    warnings.append(
                        _finding(
                            "V-05",
                            "UC-WF alignment",
                            f"{ac.get('id') or 'AC'} của {uc.get('id')} mô tả “{then[:80]}” nhưng workflow không chứa từ khóa tương ứng",
                            ["use_cases", "workflow"],
                            severity="warning",
                            suggestion="Cập nhật AC hoặc thêm bước workflow khớp hành vi.",
                        )
                    )
                    break

    for uc in ucs:
        for rid in uc.get("rule_ids") or []:
            rid_s = str(rid)
            if rid_s and rid_s not in rule_ids:
                failed.append(
                    _finding(
                        "V-06",
                        "UC-BR traceability",
                        f"UC {uc.get('id')} tham chiếu {rid_s} nhưng BR không có id đó",
                        ["use_cases", "business_rules"],
                        suggestion="Thêm BR hoặc sửa rule_ids trên UC.",
                    )
                )

    exceptions = re.findall(r"E-\d+", wf_text, flags=re.I)
    if wf_text.strip() and len(exceptions) < 1:
        warnings.append(
            _finding(
                "V-07",
                "Exception flow coverage",
                "Workflow chưa có exception flow (E-01…). Feature thường cần ít nhất một nhánh lỗi/timeout.",
                ["workflow"],
                severity="warning",
                suggestion="Thêm Exception Flows với điều kiện và handling.",
            )
        )
    elif wf_text.strip() and exceptions:
        passed.append({"check_id": "V-07", "name": "Exception flow coverage"})

    uc_actors = {str(uc.get("actor_id") or "").strip() for uc in ucs if uc.get("actor_id")}
    for aid in actor_ids:
        if aid and aid not in uc_actors and ucs:
            warnings.append(
                _finding(
                    "V-08",
                    "Actor completeness",
                    f"Actor {aid} chưa có Use Case nào",
                    ["feature_definition", "use_cases"],
                    severity="warning",
                    suggestion="Thêm Use Case cho actor này hoặc bỏ actor khỏi FD.",
                )
            )

    tps = _touchpoints(artifacts)
    if tps and ucs:
        uc_ids = {str(uc.get("id") or "") for uc in ucs}
        orphan = [
            str(tp.get("id") or tp.get("name") or "UIT")
            for tp in tps
            if tp.get("related_uc_ids")
            and not any(str(uid) in uc_ids for uid in tp.get("related_uc_ids") or [])
        ]
        if orphan:
            warnings.append(
                _finding(
                    "V-09",
                    "Touchpoint-UC mapping",
                    "UI touchpoint " + ", ".join(orphan[:6]) + " không trỏ tới UC hiện có",
                    ["ui_touchpoints", "use_cases"],
                    severity="warning",
                    suggestion="Gắn related_uc_ids khớp Use Case, hoặc xóa touchpoint mồ côi.",
                )
            )
        else:
            passed.append({"check_id": "V-09", "name": "Touchpoint-UC mapping"})

    return failed, warnings, passed
