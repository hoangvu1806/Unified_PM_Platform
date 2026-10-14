"""Per-page wiki validation status relative to last VA snapshot.

Approved (human) status is live from the wiki store.
Validation pass/fail/unchecked is frozen against ``last_validation`` —
pages approved after the last Validate stay ``unchecked``, not silent pass.

V-WIKI findings often cite a primary ``evidence_page_id`` and a
``conflict_ref`` (paired page for V-WIKI-03, BR/US id for others).
"""

from __future__ import annotations

from typing import Any, Literal

ValidationCheckStatus = Literal["pass", "fail", "unchecked"]

# Values written on WikiDocumentHit.validation_status
STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_UNCHECKED = "unchecked"

# V-WIKI-03 conflict_ref is the other wiki page_id.
_PAIR_CHECK_IDS = frozenset({"V-WIKI-03"})


def _is_wiki_error_finding(finding: dict[str, Any]) -> bool:
    check_id = str(finding.get("check_id") or "")
    if not check_id.startswith("V-WIKI"):
        return False
    # V-WIKI-05 is warning-only and must not mark pages as fail.
    severity = str(finding.get("severity") or "error").lower()
    if check_id == "V-WIKI-05" or severity == "warning":
        return False
    return True


def _finding_page_id(finding: dict[str, Any]) -> str:
    return str(
        finding.get("evidence_page_id")
        or finding.get("page_id")
        or ""
    ).strip()


def _conflict_page_ids(finding: dict[str, Any]) -> list[str]:
    """Other wiki page_id(s) in this finding (pairwise V-WIKI-03)."""
    check_id = str(finding.get("check_id") or "")
    if check_id not in _PAIR_CHECK_IDS:
        return []
    ref = str(finding.get("conflict_ref") or "").strip()
    primary = _finding_page_id(finding)
    if not ref or ref == primary:
        return []
    return [ref]


def _pages_touched_by_finding(finding: dict[str, Any]) -> set[str]:
    touched: set[str] = set()
    primary = _finding_page_id(finding)
    if primary:
        touched.add(primary)
    touched.update(_conflict_page_ids(finding))
    return touched


def findings_for_page(
    page_id: str,
    last_validation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Compact findings that cite ``page_id`` (primary or V-WIKI-03 pair)."""
    pid = str(page_id or "").strip()
    if not pid:
        return []
    last = last_validation if isinstance(last_validation, dict) else {}
    out: list[dict[str, Any]] = []
    for finding in last.get("failed_checks") or []:
        if not isinstance(finding, dict) or not _is_wiki_error_finding(finding):
            continue
        touched = _pages_touched_by_finding(finding)
        if pid not in touched:
            continue
        primary = _finding_page_id(finding)
        conflict_pages = _conflict_page_ids(finding)
        # For the pair partner view, surface the primary as the "other" page.
        other = [p for p in ([primary] + conflict_pages) if p and p != pid]
        # Non-page conflict_ref (BR id, US id, scope text) still useful.
        conflict_ref = str(finding.get("conflict_ref") or "").strip()
        if conflict_ref and conflict_ref not in other and conflict_ref != pid:
            # Keep as conflict_ref; only list as conflict_page_ids when pairwise.
            pass
        out.append(
            {
                "check_id": str(finding.get("check_id") or ""),
                "name": str(finding.get("name") or ""),
                "detail": str(finding.get("detail") or "")[:240],
                "conflict_ref": conflict_ref,
                "conflict_page_ids": other if conflict_pages or (
                    str(finding.get("check_id") or "") in _PAIR_CHECK_IDS
                ) else [],
                "suggestion": str(finding.get("suggestion") or "")[:160],
            }
        )
    return out


def wiki_validation_snapshot(last_validation: dict[str, Any] | None) -> dict[str, Any]:
    """Derive checked/failed page sets and overall wiki outcome from last VA."""
    last = last_validation if isinstance(last_validation, dict) else {}
    evidence = last.get("evidence_references") or []
    checked_ids: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("page_id") or "").strip()
        if pid:
            checked_ids.add(pid)

    failed_ids: set[str] = set()
    global_wiki_fail = False
    for finding in last.get("failed_checks") or []:
        if not isinstance(finding, dict) or not _is_wiki_error_finding(finding):
            continue
        touched = _pages_touched_by_finding(finding)
        if touched:
            failed_ids.update(touched)
            # Pair partners may not be in evidence_references — still "checked".
            checked_ids.update(touched)
        else:
            global_wiki_fail = True

    has_run = bool(last.get("validated_at") or last.get("status") or checked_ids)
    if global_wiki_fail:
        overall = "fail"
    elif failed_ids:
        overall = "fail"
    elif not has_run:
        overall = "unchecked"
    elif checked_ids:
        overall = "pass"
    else:
        # Validated but no wiki evidence — package may have passed without pages.
        overall = str(last.get("status") or "unchecked")
        if overall in {"passed", "passed_with_warnings"}:
            overall = "pass"
        elif overall in {"failed", "blocked"}:
            overall = "fail"
        else:
            overall = "unchecked"

    return {
        "checked_page_ids": checked_ids,
        "failed_page_ids": failed_ids,
        "global_wiki_fail": global_wiki_fail,
        "has_run": has_run,
        "overall": overall,
        "validated_at": last.get("validated_at"),
        "validation_status": last.get("status"),
        "last_validation": last,
        "failed_page_ids_list": sorted(failed_ids),
    }


def page_validation_status(
    page_id: str,
    *,
    snapshot: dict[str, Any],
) -> ValidationCheckStatus:
    """Return pass | fail | unchecked for one approved page_id."""
    pid = str(page_id or "").strip()
    if not pid or not snapshot.get("has_run"):
        return STATUS_UNCHECKED
    checked: set[str] = snapshot["checked_page_ids"]
    failed: set[str] = snapshot["failed_page_ids"]
    if pid not in checked:
        # Approved after last Validate (or never pulled into that run).
        return STATUS_UNCHECKED
    if pid in failed:
        return STATUS_FAIL
    if snapshot.get("global_wiki_fail"):
        # Honest: wiki failed globally; page was in the checked set.
        return STATUS_FAIL
    return STATUS_PASS


def annotate_document_hit(
    hit: dict[str, Any],
    *,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Return a copy of hit with validation_status + conflict findings set."""
    out = dict(hit)
    pid = str(out.get("page_id") or "")
    out["validation_status"] = page_validation_status(pid, snapshot=snapshot)
    findings = findings_for_page(pid, snapshot.get("last_validation"))
    out["validation_findings"] = findings
    return out


def summarize_validation_statuses(
    statuses: list[str],
    *,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """UI summary for the approved-wiki card header."""
    counts = {
        STATUS_PASS: 0,
        STATUS_FAIL: 0,
        STATUS_UNCHECKED: 0,
    }
    for s in statuses:
        key = s if s in counts else STATUS_UNCHECKED
        counts[key] += 1

    overall = snapshot.get("overall") or STATUS_UNCHECKED
    if counts[STATUS_FAIL]:
        overall = STATUS_FAIL
    elif counts[STATUS_UNCHECKED] and counts[STATUS_PASS]:
        overall = "mixed"
    elif counts[STATUS_UNCHECKED] and not counts[STATUS_PASS]:
        overall = STATUS_UNCHECKED
    elif counts[STATUS_PASS]:
        overall = STATUS_PASS

    return {
        "overall": overall,
        "counts": counts,
        "validated_at": snapshot.get("validated_at"),
        "validation_status": snapshot.get("validation_status"),
        "has_run": bool(snapshot.get("has_run")),
    }
