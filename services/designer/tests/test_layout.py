from app.generation.layout import (
    deterministic_layout_review,
    is_ignorable_overlap,
)
from app.models import LayoutFinding, LayoutReview, UiSpecification
from app.openpencil.qa import blocking_findings, clipped_instance_text, required_content_gaps, visible_text
from app.workflow.build import _summarize_layout_reviews


def specification() -> UiSpecification:
    return UiSpecification.model_validate(
        {
            "screen_name": "Checkout",
            "platform": "mobile",
            "viewport_width": 390,
            "viewport_height": 844,
            "summary": "Mobile checkout",
            "root": {"id": "root", "kind": "container", "name": "Page", "children": []},
        }
    )


def test_required_content_ignores_design_metadata_but_checks_visible_copy() -> None:
    spec = UiSpecification.model_validate(
        {
            "screen_name": "Schedule",
            "platform": "mobile",
            "viewport_width": 390,
            "viewport_height": 844,
            "summary": "Schedule",
            "root": {
                "id": "root",
                "kind": "container",
                "name": "Page",
                "content": {"composition": "Asymmetric timeline with generous whitespace"},
                "children": [
                    {
                        "id": "title",
                        "kind": "text",
                        "name": "Title",
                        "content": {"text": "Lịch học hôm nay"},
                    },
                    {
                        "id": "cta",
                        "kind": "component",
                        "name": "Button",
                        "content": {"treatment": "Filled indigo, 48px high, white label"},
                    },
                ],
            },
        }
    )

    gaps = required_content_gaps(
        spec,
        '<Frame><Text>Lịch học hôm nay</Text><Text>Đăng ký tiết học mới</Text></Frame>',
        ["Đăng ký tiết học mới"],
    )

    assert gaps == []


def test_required_content_uses_actual_canvas_text_after_inspection() -> None:
    spec = UiSpecification.model_validate(
        {
            "screen_name": "Splash",
            "platform": "mobile",
            "viewport_width": 390,
            "viewport_height": 844,
            "summary": "Splash",
            "root": {
                "id": "root",
                "kind": "container",
                "name": "Page",
                "children": [
                    {"id": "title", "kind": "text", "name": "Title", "content": {"text": "GDU-360"}}
                ],
            },
        }
    )

    gaps = required_content_gaps(
        spec,
        '<Frame><Text>GDU-360</Text></Frame>',
        rendered_text=[],
    )

    assert gaps == ["GDU-360"]
    assert blocking_findings({"content_gaps": gaps}, 390)[0]["category"] == "missing-visible-content"


def test_visible_text_ignores_hidden_nodes() -> None:
    root = {
        "type": "FRAME",
        "children": [
            {"type": "TEXT", "characters": "GDU-360", "visible": True},
            {"type": "TEXT", "characters": "Hidden", "visible": False},
        ],
    }

    assert visible_text(root) == ["GDU-360"]


def test_deterministic_review_blocks_incomplete_assembly() -> None:
    review = deterministic_layout_review(
        specification(),
        {
            "bounds": {"width": 430, "height": 800},
            "instances": 1,
            "placeholders": 1,
            "overlaps": {"summary": {"bySeverity": {"major": 1}}},
        },
        expected_instances=2,
    )

    assert review.status == "invalid"
    assert {item.category for item in review.findings} == {
        "viewport-mismatch",
        "component-coverage",
        "unbound-placeholder",
        "overlap",
    }


def test_residual_layout_findings_are_advisory_after_agent_inspection() -> None:
    result = _summarize_layout_reviews(
        [
            {
                "status": "invalid",
                "screen_name": "Deviation Intake Form",
                "findings": [
                    {
                        "severity": "error",
                        "category": "overlap",
                        "evidence": "A decorative ellipse extends outside its frame.",
                        "correction": "Review the component before approval.",
                    }
                ],
            }
        ]
    )

    assert result["status"] == "advisory"
    assert len(result["findings"]) == 1
    assert "after the page agent's final inspection" in result["summary"]


def test_deterministic_review_blocks_missing_media() -> None:
    review = deterministic_layout_review(
        specification(),
        {
            "bounds": {"width": 390, "height": 844},
            "instances": 0,
            "placeholders": 0,
            "expected_photos": 2,
            "stock_photos": 1,
        },
        expected_instances=0,
    )
    assert review.status == "invalid"
    assert [item.category for item in review.findings] == ["media-coverage"]


def test_layout_finding_severity_and_status_normalization() -> None:
    finding_major = LayoutFinding(
        severity="major",  # type: ignore
        category="overlap",
        evidence="Overlapping elements",
        correction="Adjust spacing",
    )
    assert finding_major.severity == "error"

    finding_critical = LayoutFinding(
        severity="critical",  # type: ignore
        category="clipped",
        evidence="Text cut off",
        correction="Increase container height",
    )
    assert finding_critical.severity == "error"

    finding_minor = LayoutFinding(
        severity="minor",  # type: ignore
        category="alignment",
        evidence="1px off",
        correction="Align items",
    )
    assert finding_minor.severity == "info"

    finding_moderate = LayoutFinding(
        severity="moderate",  # type: ignore
        category="contrast",
        evidence="Low contrast",
        correction="Darken text",
    )
    assert finding_moderate.severity == "warning"

    review_passed = LayoutReview(
        status="passed",  # type: ignore
        summary="Looks great",
        findings=[finding_minor],
    )
    assert review_passed.status == "valid"

    review_failed = LayoutReview(
        status="failed",  # type: ignore
        summary="Has issues",
        findings=[finding_major],
    )
    assert review_failed.status == "invalid"


def test_deterministic_review_unwraps_nested_root_bounds() -> None:
    review = deterministic_layout_review(
        specification(),
        {
            "root_bounds": {
                "id": "0:2077",
                "bounds": {"x": 0, "y": 0, "width": 390, "height": 844},
            },
            "instances": 0,
            "placeholders": 0,
        },
        expected_instances=0,
    )
    assert review.status == "valid"
    assert not any(f.category == "telemetry" for f in review.findings)
    assert not any(f.category == "viewport-mismatch" for f in review.findings)


def test_deterministic_review_filters_internal_icon_overlaps() -> None:
    telemetry = {
        "bounds": {"width": 390, "height": 844},
        "instances": 0,
        "placeholders": 0,
        "overlaps": {
            "overlaps": [
                {
                    "category": "sibling-overlap",
                    "severity": "major",
                    "nodeA": {"name": "path", "type": "VECTOR", "parentId": "0:icon1"},
                    "nodeB": {"name": "path", "type": "VECTOR", "parentId": "0:icon1"},
                },
                {
                    "category": "parent-overflow",
                    "severity": "major",
                    "nodeA": {"name": "path", "type": "VECTOR", "parentId": "0:icon1"},
                    "nodeB": {"name": "Icon / home", "type": "FRAME", "id": "0:icon1"},
                },
            ],
            "summary": {"bySeverity": {"major": 2}},
        },
    }
    review = deterministic_layout_review(specification(), telemetry, expected_instances=0)
    assert review.status == "valid"
    assert not any(f.category == "overlap" for f in review.findings)


def test_deterministic_review_flags_real_element_overlaps() -> None:
    telemetry = {
        "bounds": {"width": 390, "height": 844},
        "instances": 0,
        "placeholders": 0,
        "overlaps": {
            "overlaps": [
                {
                    "category": "sibling-overlap",
                    "severity": "major",
                    "nodeA": {"name": "Bottom Nav", "type": "FRAME", "parentId": "0:root"},
                    "nodeB": {"name": "Event Card 2", "type": "FRAME", "parentId": "0:section"},
                },
            ],
            "summary": {"bySeverity": {"major": 1}},
        },
    }
    review = deterministic_layout_review(specification(), telemetry, expected_instances=0)
    assert review.status == "invalid"
    assert any(f.category == "overlap" for f in review.findings)


def test_deterministic_review_filters_minor_parent_overflow_shadows() -> None:
    minor_shadow_overflow = {
        "category": "parent-overflow",
        "severity": "minor",
        "ratio": 0.05,
        "area": 790,
        "message": 'Node "Frame" extends 790px outside parent "Trường nhập liệu Email"',
    }
    assert is_ignorable_overlap(minor_shadow_overflow) is True

    telemetry = {
        "bounds": {"width": 390, "height": 844},
        "instances": 0,
        "placeholders": 0,
        "overlaps": {
            "overlaps": [minor_shadow_overflow],
            "summary": {"bySeverity": {"minor": 1}},
        },
    }
    review = deterministic_layout_review(specification(), telemetry, expected_instances=0)
    assert review.status == "valid"
    assert not any(f.category == "overlap" for f in review.findings)


def test_instance_text_overflow_blocks_visual_completion() -> None:
    telemetry = {
        "root_bounds": {"bounds": {"width": 390}},
        "overlaps": {
            "overlaps": [
                {
                    "category": "parent-overflow",
                    "severity": "critical",
                    "message": "Button label extends outside its instance",
                    "nodeA": {"name": "Text", "type": "TEXT"},
                    "nodeB": {"name": "Primary Button", "type": "INSTANCE"},
                },
                {
                    "category": "parent-overflow",
                    "severity": "critical",
                    "message": "Library guide extends outside its instance",
                    "nodeA": {"name": "Min Width", "type": "LINE"},
                    "nodeB": {"name": "Primary Button", "type": "INSTANCE"},
                },
            ]
        },
    }
    findings = blocking_findings(telemetry, 390)
    assert [item["message"] for item in findings] == ["Button label extends outside its instance"]


def test_clipped_instance_text_detects_hidden_button_label() -> None:
    root = {
        "type": "FRAME",
        "children": [
            {
                "type": "INSTANCE",
                "name": "Button",
                "width": 208,
                "height": 40,
                "children": [
                    {"type": "TEXT", "characters": "Save", "x": 8, "y": 58, "width": 80, "height": 24}
                ],
            }
        ],
    }
    assert clipped_instance_text(root) == [{"instance": "Button", "text": "Save"}]
