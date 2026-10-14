"""Unit tests: per-page wiki validation_status vs last Validate snapshot."""

from managers.service.wiki_validation_status import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_UNCHECKED,
    annotate_document_hit,
    page_validation_status,
    summarize_validation_statuses,
    wiki_validation_snapshot,
)


def test_no_validation_means_all_unchecked():
    snap = wiki_validation_snapshot(None)
    assert snap["has_run"] is False
    assert page_validation_status("PAGE-A", snapshot=snap) == STATUS_UNCHECKED


def test_checked_page_pass_when_no_wiki_fail():
    last = {
        "status": "passed",
        "validated_at": "2026-09-08T01:00:00+00:00",
        "evidence_references": [
            {"page_id": "PAGE-A", "title": "A"},
            {"page_id": "PAGE-B", "title": "B"},
        ],
        "failed_checks": [],
    }
    snap = wiki_validation_snapshot(last)
    assert page_validation_status("PAGE-A", snapshot=snap) == STATUS_PASS
    assert page_validation_status("PAGE-B", snapshot=snap) == STATUS_PASS
    # Approved after last Validate → unchecked, not silent pass
    assert page_validation_status("PAGE-NEW", snapshot=snap) == STATUS_UNCHECKED


def test_failing_v_wiki_marks_page_fail():
    last = {
        "status": "failed",
        "validated_at": "2026-09-08T01:00:00+00:00",
        "evidence_references": [
            {"page_id": "PAGE-BAD", "title": "Bad"},
            {"page_id": "PAGE-OK", "title": "Ok"},
        ],
        "failed_checks": [
            {
                "check_id": "V-WIKI-01",
                "severity": "error",
                "evidence_page_id": "PAGE-BAD",
                "name": "threshold",
                "detail": "disagree",
            }
        ],
    }
    snap = wiki_validation_snapshot(last)
    assert page_validation_status("PAGE-BAD", snapshot=snap) == STATUS_FAIL
    assert page_validation_status("PAGE-OK", snapshot=snap) == STATUS_PASS
    assert page_validation_status("PAGE-LATER", snapshot=snap) == STATUS_UNCHECKED


def test_v_wiki_05_warning_does_not_fail_page():
    last = {
        "status": "passed_with_warnings",
        "validated_at": "2026-09-08T01:00:00+00:00",
        "evidence_references": [{"page_id": "PAGE-A"}],
        "failed_checks": [],
        "warnings": [
            {
                "check_id": "V-WIKI-05",
                "severity": "warning",
                "evidence_page_id": "PAGE-A",
            }
        ],
    }
    snap = wiki_validation_snapshot(last)
    assert page_validation_status("PAGE-A", snapshot=snap) == STATUS_PASS


def test_global_wiki_fail_marks_checked_pages_fail():
    last = {
        "status": "failed",
        "validated_at": "2026-09-08T01:00:00+00:00",
        "evidence_references": [{"page_id": "PAGE-A"}, {"page_id": "PAGE-B"}],
        "failed_checks": [
            {
                "check_id": "V-WIKI-03",
                "severity": "error",
                "name": "cross-wiki",
                "detail": "contradiction without page id",
            }
        ],
    }
    snap = wiki_validation_snapshot(last)
    assert snap["global_wiki_fail"] is True
    assert page_validation_status("PAGE-A", snapshot=snap) == STATUS_FAIL
    assert page_validation_status("PAGE-NEW", snapshot=snap) == STATUS_UNCHECKED


def test_v_wiki_03_marks_both_pages_and_exposes_pair():
    last = {
        "status": "failed",
        "validated_at": "2026-09-08T01:00:00+00:00",
        "evidence_references": [
            {"page_id": "PAGE-A", "title": "A"},
            {"page_id": "PAGE-B", "title": "B"},
        ],
        "failed_checks": [
            {
                "check_id": "V-WIKI-03",
                "severity": "error",
                "name": "Wiki contradicts wiki",
                "detail": "Hai trang approved mâu thuẫn: PAGE-A vs PAGE-B.",
                "evidence_page_id": "PAGE-A",
                "conflict_ref": "PAGE-B",
            }
        ],
    }
    snap = wiki_validation_snapshot(last)
    assert page_validation_status("PAGE-A", snapshot=snap) == STATUS_FAIL
    assert page_validation_status("PAGE-B", snapshot=snap) == STATUS_FAIL
    hit_a = annotate_document_hit({"page_id": "PAGE-A", "title": "A"}, snapshot=snap)
    hit_b = annotate_document_hit({"page_id": "PAGE-B", "title": "B"}, snapshot=snap)
    assert hit_a["validation_findings"][0]["check_id"] == "V-WIKI-03"
    assert hit_a["validation_findings"][0]["conflict_page_ids"] == ["PAGE-B"]
    assert hit_b["validation_findings"][0]["conflict_page_ids"] == ["PAGE-A"]


def test_annotate_and_summary_mixed():
    last = {
        "status": "failed",
        "validated_at": "2026-09-08T01:00:00+00:00",
        "evidence_references": [{"page_id": "PAGE-A"}],
        "failed_checks": [
            {
                "check_id": "V-WIKI-02",
                "severity": "error",
                "page_id": "PAGE-A",
            }
        ],
    }
    snap = wiki_validation_snapshot(last)
    docs = [
        annotate_document_hit({"page_id": "PAGE-A", "title": "A"}, snapshot=snap),
        annotate_document_hit({"page_id": "PAGE-NEW", "title": "New"}, snapshot=snap),
    ]
    assert docs[0]["validation_status"] == STATUS_FAIL
    assert docs[1]["validation_status"] == STATUS_UNCHECKED
    # Human approval field untouched
    assert "status" not in docs[0] or docs[0].get("status") != STATUS_FAIL
    summary = summarize_validation_statuses(
        [d["validation_status"] for d in docs],
        snapshot=snap,
    )
    assert summary["overall"] == STATUS_FAIL
    assert summary["counts"][STATUS_FAIL] == 1
    assert summary["counts"][STATUS_UNCHECKED] == 1
