"""Firm wiki Validate checks (V-WIKI-01..05). Python outcome only — cite page_id."""

from __future__ import annotations

import re
from typing import Any

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
        "wiki",
        "page",
    }
)

# Policy / threshold vocabulary (broader than triệu / phê duyệt only).
_POLICY_MARKERS = (
    "triệu",
    "threshold",
    "phê duyệt",
    "approval",
    "phải có",
    "không được",
    "must not",
    "must ",
    "giảm giá",
    "discount",
    "cutoff",
    "hạn mức",
    "tối đa",
    "tối thiểu",
    "phần trăm",
    "%",
    "vnd",
    "usd",
)

_NEGATION_PAIRS = (
    ("không được", "được phép"),
    ("không được", "cho phép"),
    ("blocked", "allowed"),
    ("block", "open"),
    ("must not", "must "),
    ("chặn", "cho phép"),
    ("từ chối", "chấp nhận"),
    ("reject", "approve"),
    ("closed", "open"),
    ("bị khóa", "vẫn mở"),
)


def _tokens(text: str) -> set[str]:
    return {
        tok.lower()
        for tok in re.findall(r"[A-Za-zÀ-ỹ0-9]{4,}", text or "")
        if tok.lower() not in _STOP
    }


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _actor_ids(fd: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for actor in fd.get("actors") or []:
        raw = str(actor).strip()
        aid = raw.split(":", 1)[0].strip() if ":" in raw else raw
        if aid:
            ids.add(aid.upper())
    return ids


def _extract_policy_numbers(text: str) -> set[str]:
    """Normalize amounts / percents / cutoffs for comparison."""
    low = _norm(text)
    found: set[str] = set()
    for m in re.finditer(
        r"(\d+(?:[.,]\d+)?)\s*(triệu|%|percent|phần trăm|vnd|usd|giờ|phút|\bh\b)?",
        low,
    ):
        num = m.group(1).replace(",", ".")
        unit = (m.group(2) or "").strip()
        found.add(f"{num}:{unit}" if unit else num)
    return found


def _has_policy_signal(text: str) -> bool:
    low = _norm(text)
    if any(m in low for m in _POLICY_MARKERS):
        return True
    return bool(_extract_policy_numbers(text))


def _numbers_disagree(a: str, b: str) -> bool:
    na, nb = _extract_policy_numbers(a), _extract_policy_numbers(b)
    if not na or not nb:
        return False
    # Same unit families present but values differ.
    for item in na:
        num, _, unit = item.partition(":")
        peers = {x for x in nb if x.endswith(f":{unit}")} if unit else {
            x for x in nb if ":" not in x or x.startswith(num)
        }
        if not peers:
            continue
        if item not in nb and peers:
            # Different numeric value with overlapping unit context.
            peer_nums = {p.partition(":")[0] for p in peers}
            if num not in peer_nums:
                return True
    # Also: wiki has amounts none of which appear in BR text at all.
    br_blob = _norm(b)
    for item in na:
        num = item.partition(":")[0]
        if num and num not in br_blob:
            return True
    return False


def _opposite_outcome(a: str, b: str) -> bool:
    la, lb = _norm(a), _norm(b)
    for neg, pos in _NEGATION_PAIRS:
        if (neg in la and pos in lb) or (pos in la and neg in lb):
            return True
        if (neg in la and neg not in lb and pos.replace(" ", "") in lb.replace(" ", "")):
            return True
    # "phải" vs "không cần" / "không phải"
    if ("không cần" in la and "phải" in lb) or ("không cần" in lb and "phải" in la):
        return True
    if ("không phải" in la and "phải" in lb) or ("không phải" in lb and "phải" in la):
        return True
    return False


def _topic_overlap(a: str, b: str, *, min_shared: int = 2) -> bool:
    return len(_tokens(a) & _tokens(b)) >= min_shared


def _finding(
    check_id: str,
    name: str,
    detail: str,
    sections: list[str],
    *,
    page_id: str,
    page_title: str = "",
    severity: str = "error",
    suggestion: str = "",
    conflict_ref: str = "",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "check_id": check_id,
        "name": name,
        "severity": severity,
        "detail": detail,
        "suggestion": suggestion
        or "Sửa wiki (approve bản đúng) hoặc chỉnh package BA rồi re-Validate.",
        "affected_sections": sections,
        "evidence_page_id": page_id,
        "page_id": page_id,
    }
    if page_title:
        out["evidence_page_title"] = page_title
    if conflict_ref:
        out["conflict_ref"] = conflict_ref
    return out


def wiki_contradicts_br(page_body: str, br_text: str) -> bool:
    """V-WIKI-01: wiki policy numbers / thresholds disagree with BR."""
    if not br_text or br_text.strip() in {"", "[]"}:
        return False
    if not _has_policy_signal(page_body):
        return False
    body_l = _norm(page_body)
    br_l = _norm(br_text)
    if _numbers_disagree(page_body, br_text):
        return True
    # Approval / must-have language present in wiki but absent from BR.
    if any(m in body_l for m in ("phê duyệt", "approval")) and not any(
        m in br_l for m in ("phê duyệt", "approval")
    ):
        return True
    if "discount" in body_l or "giảm giá" in body_l:
        if "discount" not in br_l and "giảm giá" not in br_l:
            if _extract_policy_numbers(page_body) and not (
                _extract_policy_numbers(page_body) <= _extract_policy_numbers(br_text)
            ):
                return True
    return False


def run_firm_wiki_checks(
    *,
    pages: list[dict[str, Any]],
    artifacts: dict[str, Any],
) -> tuple[list[dict], list[dict]]:
    """Return (failed_errors, warnings) for approved wiki pages (full body)."""
    failed: list[dict] = []
    warnings: list[dict] = []
    fd = artifacts.get("feature_definition") or {}
    if not isinstance(fd, dict):
        fd = {}
    rules = artifacts.get("business_rules") or []
    br_text = "\n".join(
        str(r.get("statement") or r) if isinstance(r, dict) else str(r) for r in rules
    )
    br_ids = [
        str(r.get("id"))
        for r in rules
        if isinstance(r, dict) and r.get("id")
    ]
    ucs = [
        u
        for u in (artifacts.get("use_cases") or [])
        if isinstance(u, dict)
    ]
    actor_ids = _actor_ids(fd)
    scope_out = [str(x).strip() for x in (fd.get("scope_out") or []) if str(x).strip()]
    wiki_blob = "\n".join(
        f"{p.get('title') or ''}\n{p.get('body') or ''}" for p in pages
    )

    # V-WIKI-01 wiki vs BR
    for page in pages:
        body = str(page.get("body") or "")
        pid = str(page.get("page_id") or "")
        title = str(page.get("title") or "")
        if wiki_contradicts_br(body, br_text):
            failed.append(
                _finding(
                    "V-WIKI-01",
                    "Wiki contradicts BR",
                    (
                        f"Wiki {pid} có ngưỡng/policy (số, %, cutoff, phê duyệt) "
                        "không khớp Business Rules"
                    ),
                    ["business_rules"],
                    page_id=pid,
                    page_title=title,
                    conflict_ref=",".join(br_ids[:6]) or "BR",
                )
            )

    # V-WIKI-02 wiki vs User Story / AC
    for page in pages:
        body = str(page.get("body") or "")
        pid = str(page.get("page_id") or "")
        title = str(page.get("title") or "")
        for uc in ucs:
            uid = str(uc.get("id") or "US")
            story_parts = [str(uc.get("statement") or "")]
            for ac in uc.get("acceptance_criteria") or []:
                if isinstance(ac, dict):
                    story_parts.append(
                        " ".join(
                            str(ac.get(k) or "")
                            for k in ("given", "when", "then")
                        )
                    )
            story_text = "\n".join(story_parts)
            if not _topic_overlap(body, story_text):
                continue
            if _opposite_outcome(body, story_text) or _numbers_disagree(body, story_text):
                failed.append(
                    _finding(
                        "V-WIKI-02",
                        "Wiki contradicts User Story/AC",
                        (
                            f"Wiki {pid} mâu thuẫn với {uid} / AC "
                            "(cùng topic, outcome hoặc số liệu ngược)"
                        ),
                        ["use_cases"],
                        page_id=pid,
                        page_title=title,
                        conflict_ref=uid,
                    )
                )
                break

    # V-WIKI-03 wiki vs wiki
    for i, a in enumerate(pages):
        for b in pages[i + 1 :]:
            body_a = str(a.get("body") or "")
            body_b = str(b.get("body") or "")
            if not _topic_overlap(body_a, body_b) and not _topic_overlap(
                str(a.get("title") or ""), str(b.get("title") or ""), min_shared=1
            ):
                # Still compare if both have policy numbers in same unit.
                if not (
                    _extract_policy_numbers(body_a) and _extract_policy_numbers(body_b)
                ):
                    continue
            contradict = _opposite_outcome(body_a, body_b) or _numbers_disagree(
                body_a, body_b
            )
            # Actor permission clash: one page grants, other forbids same actor verb.
            if not contradict:
                continue
            pa = str(a.get("page_id") or "")
            pb = str(b.get("page_id") or "")
            failed.append(
                _finding(
                    "V-WIKI-03",
                    "Wiki contradicts wiki",
                    (
                        f"Hai trang approved mâu thuẫn: {pa} vs {pb}. "
                        "Trang mới hơn không tự thắng — sửa wiki rồi re-Validate."
                    ),
                    ["business_rules", "use_cases"],
                    page_id=pa,
                    page_title=str(a.get("title") or ""),
                    conflict_ref=pb,
                )
            )

    # V-WIKI-04 scope_out / unknown actor as in-scope
    for page in pages:
        body = str(page.get("body") or "")
        body_l = _norm(body)
        pid = str(page.get("page_id") or "")
        title = str(page.get("title") or "")
        for item in scope_out:
            item_l = _norm(item)
            if len(item_l) < 4:
                continue
            if item_l in body_l and any(
                cue in body_l
                for cue in (
                    "hỗ trợ",
                    "bao gồm",
                    "scope in",
                    "trong phạm vi",
                    "phải",
                    "cho phép",
                    "implements",
                    "supports",
                )
            ):
                failed.append(
                    _finding(
                        "V-WIKI-04",
                        "Wiki asserts scope_out as in-scope",
                        f"Wiki {pid} mô tả “{item}” như in-scope nhưng FD scope_out có mục này",
                        ["feature_definition"],
                        page_id=pid,
                        page_title=title,
                        conflict_ref=item[:80],
                    )
                )
                break
        # Unknown ACT-* presented as process actor.
        for m in re.finditer(r"\b(ACT-[A-Z0-9-]+)\b", body, flags=re.I):
            aid = m.group(1).upper()
            if actor_ids and aid not in actor_ids:
                # Only error if framed as participant / must act.
                window = body_l[max(0, m.start() - 40) : m.end() + 40]
                if any(
                    cue in window
                    for cue in ("actor", "vai trò", "phải", "thực hiện", "lane", "bước")
                ):
                    failed.append(
                        _finding(
                            "V-WIKI-04",
                            "Wiki names unknown actor as in-scope",
                            f"Wiki {pid} nêu {aid} như actor in-scope nhưng FD không có",
                            ["feature_definition"],
                            page_id=pid,
                            page_title=title,
                            conflict_ref=aid,
                        )
                    )
                    break

    # V-WIKI-05 coverage gap (warning only)
    wiki_l = _norm(wiki_blob)
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or "")
        stmt = str(rule.get("statement") or "")
        if not rid or not stmt:
            continue
        toks = _tokens(stmt)
        if len(toks) < 2:
            continue
        if rid.lower() in wiki_l:
            continue
        if not any(tok in wiki_l for tok in toks):
            warnings.append(
                _finding(
                    "V-WIKI-05",
                    "Wiki coverage gap",
                    f"Wiki chưa đề cập ràng buộc {rid} (“{stmt[:80]}”)",
                    ["business_rules"],
                    page_id="",
                    severity="warning",
                    suggestion="Bổ sung / approve wiki hoặc chấp nhận gap (không chặn Export).",
                    conflict_ref=rid,
                )
            )
    for uc in ucs:
        uid = str(uc.get("id") or "")
        stmt = str(uc.get("statement") or "")
        toks = _tokens(stmt)
        if not uid or len(toks) < 2:
            continue
        if uid.lower() in wiki_l:
            continue
        if not any(tok in wiki_l for tok in toks):
            warnings.append(
                _finding(
                    "V-WIKI-05",
                    "Wiki coverage gap",
                    f"Wiki im lặng về User Story {uid}",
                    ["use_cases"],
                    page_id="",
                    severity="warning",
                    suggestion="Coverage gap — không chặn Export.",
                    conflict_ref=uid,
                )
            )

    return failed, warnings
