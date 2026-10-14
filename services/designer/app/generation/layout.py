from typing import Any

from ..models import LayoutFinding, LayoutReview, UiSpecification


def extract_measurable_bounds(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Extract width and height from telemetry, unwrapping nested node_bounds or page_bounds."""
    for key in ("root_bounds", "bounds"):
        val = telemetry.get(key)
        if isinstance(val, dict):
            if "bounds" in val and isinstance(val["bounds"], dict):
                inner = val["bounds"]
                if any(k in inner for k in ("width", "w", "height", "h")):
                    return inner
            if any(k in val for k in ("width", "w", "height", "h")):
                return val
    return {}


def is_icon_internal_overlap(item: dict[str, Any]) -> bool:
    """Check if an overlap finding is an internal vector path detail inside an icon.
    OpenPencil expands SVG icons into multiple intersecting <path> vector nodes.
    These internal sub-paths naturally cross or share the icon container frame,
    and should not be treated as blocking UI layout errors.
    """
    node_a = item.get("nodeA") or {}
    node_b = item.get("nodeB") or {}
    name_a = str(node_a.get("name", "")).lower()
    name_b = str(node_b.get("name", "")).lower()
    type_a = str(node_a.get("type", "")).upper()
    type_b = str(node_b.get("type", "")).upper()

    # 1. Two vector path elements (inside icons, illustrations, or markers)
    if (name_a == "path" or type_a == "VECTOR") and (name_b == "path" or type_b == "VECTOR"):
        return True

    # 2. Vector path element intersecting its parent icon frame
    if (name_a == "path" or type_a == "VECTOR") and (
        "icon" in name_b or (type_b == "FRAME" and node_a.get("parentId") == node_b.get("id"))
    ):
        return True
    if (name_b == "path" or type_b == "VECTOR") and (
        "icon" in name_a or (type_a == "FRAME" and node_b.get("parentId") == node_a.get("id"))
    ):
        return True

    # 3. Lucide / Iconify sub-node overlaps
    if "icon /" in name_a or "icon /" in name_b or "icon:" in name_a or "icon:" in name_b:
        if type_a == "VECTOR" or type_b == "VECTOR" or name_a == "path" or name_b == "path":
            return True

    return False


def is_ignorable_overlap(item: dict[str, Any]) -> bool:
    """Check if an overlap finding is benign or ignorable:
    1. Internal vector path detail inside an icon.
    2. Minor parent overflow (e.g. drop shadow, border stroke, subpixel rounding)
       where OpenPencil marked severity as minor/info or overflow ratio <= 10%.
    """
    if is_icon_internal_overlap(item):
        return True

    category = str(item.get("category", "")).lower()
    severity = str(item.get("severity", "")).lower()
    ratio = item.get("ratio")

    if category == "parent-overflow":
        if severity in ("minor", "info"):
            return True
        if isinstance(ratio, int | float) and ratio <= 0.1:
            return True

    return False


def deterministic_layout_review(
    specification: UiSpecification,
    telemetry: dict[str, Any],
    expected_instances: int,
) -> LayoutReview:
    findings: list[LayoutFinding] = []
    bounds = extract_measurable_bounds(telemetry)
    width = _number(bounds, "width", "w")
    height = _number(bounds, "height", "h")
    if width is None or height is None:
        findings.append(
            LayoutFinding(
                severity="error",
                category="telemetry",
                evidence="OpenPencil did not return measurable page bounds.",
                correction="Re-open the output document and repeat layout inspection.",
            )
        )
    elif abs(width - specification.viewport_width) > 2:
        findings.append(
            LayoutFinding(
                severity="error",
                category="viewport-mismatch",
                node_ids=[str(telemetry.get("root_node_id", ""))],
                evidence=(f"Page width {width:.1f}px does not match viewport {specification.viewport_width}px."),
                correction="Set the root width or recompose wide rows for the target viewport.",
            )
        )

    def _safe_count(val: Any) -> int:
        if val is None:
            return 0
        if isinstance(val, list | tuple | dict | set):
            return len(val)
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    instances = _safe_count(telemetry.get("instances", 0))
    if instances != expected_instances:
        findings.append(
            LayoutFinding(
                severity="error",
                category="component-coverage",
                evidence=f"Created {instances} of {expected_instances} resolved component instances.",
                correction="Restore missing placeholders and insert every approved binding.",
            )
        )

    placeholders = _safe_count(telemetry.get("placeholders", 0))
    if placeholders:
        findings.append(
            LayoutFinding(
                severity="error",
                category="unbound-placeholder",
                evidence=f"{placeholders} component placeholders remain on the generated page.",
                correction="Resolve or explicitly remove every placeholder before final review.",
            )
        )

    expected_photos = _safe_count(telemetry.get("expected_photos", 0))
    stock_photos = _safe_count(telemetry.get("stock_photos", 0))
    if stock_photos < expected_photos:
        findings.append(
            LayoutFinding(
                severity="error",
                category="media-coverage",
                evidence=f"Applied {stock_photos} of {expected_photos} required images.",
                correction="Apply an image to every media node or remove the unused node.",
            )
        )

    overlap = telemetry.get("overlaps") or {}
    overlap_list = overlap.get("overlaps")
    if isinstance(overlap_list, list):
        filtered = [
            item for item in overlap_list if not is_icon_internal_overlap(item) and not is_ignorable_overlap(item)
        ]
        severe = sum(1 for item in filtered if str(item.get("severity", "")).lower() in ("critical", "major"))
    else:
        summary = overlap.get("summary") or {}
        by_severity = summary.get("bySeverity") or summary.get("by_severity") or {}
        severe = int(by_severity.get("critical", 0)) + int(by_severity.get("major", 0))

    if severe:
        findings.append(
            LayoutFinding(
                severity="error",
                category="overlap",
                evidence=f"OpenPencil detected {severe} major or critical overlap findings.",
                correction="Fix unintended intersections and parent overflow before approval.",
            )
        )

    touch_targets = telemetry.get("small_touch_targets") or []
    if touch_targets and specification.platform in {"mobile", "responsive"}:
        findings.append(
            LayoutFinding(
                severity="warning",
                category="touch-target",
                node_ids=[str(item.get("id")) for item in touch_targets[:12]],
                evidence=f"{len(touch_targets)} interactive instances are smaller than 44×44px.",
                correction="Use a larger component size or increase its surrounding hit area.",
            )
        )

    status = "invalid" if any(item.severity == "error" for item in findings) else "valid"
    summary_text = (
        "Deterministic layout checks found blocking issues."
        if status == "invalid"
        else "Deterministic geometry and binding checks passed."
    )
    return LayoutReview(status=status, summary=summary_text, findings=findings)


def _number(value: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, int | float):
            return float(item)
    return None
