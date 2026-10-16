from typing import Any

from mcp import ClientSession

from .helpers import small_instances


def required_content_gaps(
    specification: Any,
    live_jsx: str,
    component_text: list[str] | None = None,
    rendered_text: list[str] | None = None,
) -> list[str]:
    """Find approved user-visible copy missing from the rendered page.

    Design intent belongs in container/component metadata and must never become
    a literal-string rendering rule. Text nodes and resolved component labels
    are the two semantic sources of visible copy.
    """
    expected: list[str] = []

    def collect_value(value: Any) -> None:
        if isinstance(value, dict):
            for nested_value in value.values():
                collect_value(nested_value)
        elif isinstance(value, list):
            for item in value:
                collect_value(item)
        elif isinstance(value, str | int | float):
            text = " ".join(str(value).split()).strip()
            if text and not text.startswith("#"):
                expected.append(text)

    def visit(node: Any) -> None:
        if node.kind == "text":
            collect_value(node.content.get("text"))
        for child in node.children:
            visit(child)

    visit(specification.root)
    collect_value(component_text or [])
    # JSX can contain a Text declaration that OpenPencil failed to materialize
    # (zero-size, invisible, unsupported nesting, etc.). After inspection use
    # the actual canvas text instead of trusting source JSX alone.
    source = " ".join(rendered_text) if rendered_text is not None else live_jsx
    rendered = " ".join(source.split()).casefold()
    return list(dict.fromkeys(value for value in expected if value.casefold() not in rendered))[:20]


def blocking_findings(telemetry: dict[str, Any], viewport_width: int) -> list[dict[str, Any]]:
    """Return objective content and layout failures that block completion."""
    findings: list[dict[str, Any]] = []
    root_bounds = telemetry.get("root_bounds") or {}
    if isinstance(root_bounds.get("bounds"), dict):
        root_bounds = root_bounds["bounds"]
    width = root_bounds.get("width", root_bounds.get("w"))
    if isinstance(width, int | float) and abs(width - viewport_width) > 2:
        findings.append(
            {
                "category": "viewport-width",
                "message": (f"Root width is {width:g}px; the approved viewport is {viewport_width}px."),
            }
        )
    placeholders = int(telemetry.get("placeholders", 0))
    if placeholders:
        findings.append(
            {
                "category": "unmounted-component",
                "message": f"{placeholders} component mount(s) are still empty.",
            }
        )
    content_gaps = telemetry.get("content_gaps") or []
    if content_gaps:
        findings.append(
            {
                "category": "missing-visible-content",
                "message": f"Approved visible copy is missing from the canvas: {content_gaps[:8]}",
            }
        )
    # Composer-authored copy is editable. Exact string differences are shown
    # to the designer, but cannot alone veto an otherwise correct composition.
    clipped_text = telemetry.get("clipped_instance_text") or []
    if clipped_text:
        findings.append(
            {
                "category": "clipped-component-text",
                "message": f"Visible text falls outside a mounted component: {clipped_text[:6]}",
            }
        )
    for item in telemetry.get("component_styles") or []:
        if item.get("underfill"):
            findings.append(
                {
                    "category": "component-underfill",
                    "message": f"{item['name']} does not visually fill its mount frame.",
                    "mount_id": item.get("mount_id"),
                    "instance_id": item.get("instance_id"),
                }
            )
    overlaps = telemetry.get("overlaps", {}).get("overlaps", [])
    for item in overlaps:
        if item.get("category") != "parent-overflow" or item.get("severity") != "critical":
            continue
        parent = item.get("nodeB", {})
        child = item.get("nodeA", {})
        # Ignore invisible library guides, but never hide visible text escaping
        # from a mounted instance: the designer can pick or resize that binding.
        child_type = child.get("type")
        if parent.get("type") == "INSTANCE" and child_type != "TEXT":
            continue
        if child_type not in {"FRAME", "COMPONENT", "INSTANCE", "TEXT"}:
            continue
        if child_type == "TEXT":
            findings.append(
                {
                    "category": "parent-overflow",
                    "message": item.get("message", "Visible text exceeds its parent."),
                    "node": child.get("name"),
                    "parent": parent.get("name"),
                }
            )
    return findings[:12]


def clipped_instance_text(root: dict[str, Any]) -> list[dict[str, Any]]:
    """Find visible text whose geometry falls outside a design-system instance."""
    findings: list[dict[str, Any]] = []

    def inspect_instance(instance: dict[str, Any]) -> None:
        width = float(instance.get("width") or 0)
        height = float(instance.get("height") or 0)

        def visit(node: dict[str, Any], offset_x: float, offset_y: float) -> None:
            x = offset_x + float(node.get("x") or 0)
            y = offset_y + float(node.get("y") or 0)
            if node.get("type") == "TEXT" and node.get("visible", True):
                text_width = float(node.get("width") or 0)
                text_height = float(node.get("height") or 0)
                tol = 2.0  # text boxes round line-height; only real clipping blocks
                if x < -tol or y < -tol or x + text_width > width + tol or y + text_height > height + tol:
                    findings.append(
                        {
                            "instance": instance.get("name"),
                            "text": node.get("characters") or node.get("name"),
                        }
                    )
            for child in node.get("children", []):
                visit(child, x, y)

        for child in instance.get("children", []):
            visit(child, 0, 0)

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") == "INSTANCE":
            inspect_instance(node)
        for child in node.get("children", []):
            walk(child)

    walk(root)
    return findings[:20]


def visible_text(root: dict[str, Any]) -> list[str]:
    """Collect text that actually exists and is visible on the canvas."""
    result: list[str] = []

    def walk(node: dict[str, Any], parent_visible: bool = True) -> None:
        is_visible = (
            parent_visible
            and node.get("visible", True) is not False
            and float(node.get("opacity", 1) or 0) > 0
        )
        if is_visible and node.get("type") == "TEXT":
            value = " ".join(str(node.get("characters") or "").split()).strip()
            if value:
                result.append(value)
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                walk(child, is_visible)

    walk(root)
    return result


def component_styles(root: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose actual mounted colors, labels and sizes without returning deep trees."""
    result: list[dict[str, Any]] = []

    def hex_fill(node: dict[str, Any]) -> str:
        for fill in node.get("fills") or []:
            color = fill.get("color") if isinstance(fill, dict) else None
            if isinstance(color, dict) and fill.get("visible", True):
                return "#" + "".join(
                    f"{max(0, min(255, round(float(color.get(channel, 0)) * 255))):02X}"
                    for channel in ("r", "g", "b")
                )
        return ""

    def visit(node: dict[str, Any]) -> None:
        if str(node.get("name", "")).startswith("component::"):
            instance = next((child for child in node.get("children", []) if child.get("type") == "INSTANCE"), None)
            if instance:
                colors: list[str] = []
                surfaces: list[dict[str, Any]] = []
                texts: list[dict[str, Any]] = []
                max_surface_width = 0.0

                def collect(child: dict[str, Any]) -> None:
                    nonlocal max_surface_width
                    color = hex_fill(child)
                    if color and color not in colors and len(colors) < 5:
                        colors.append(color)
                    if color and child.get("type") != "TEXT":
                        max_surface_width = max(max_surface_width, float(child.get("width") or 0))
                    if color and child.get("type") != "TEXT" and len(surfaces) < 6:
                        surfaces.append(
                            {
                                "id": child.get("id"),
                                "name": child.get("name"),
                                "color": color,
                                "width": child.get("width"),
                                "height": child.get("height"),
                            }
                        )
                    if child.get("type") == "TEXT" and len(texts) < 8:
                        texts.append(
                            {
                                "id": child.get("id"),
                                "text": child.get("characters", ""),
                                "color": color,
                                "width": child.get("width"),
                                "height": child.get("height"),
                            }
                        )
                    for nested in child.get("children", []):
                        collect(nested)

                collect(instance)
                mount_width = float(node.get("width") or 0)
                instance_width = float(instance.get("width") or 0)
                result.append(
                    {
                        "name": node["name"].removeprefix("component::"),
                        "mount_id": node.get("id"),
                        "instance_id": instance.get("id"),
                        "mount_size": [mount_width, node.get("height")],
                        "instance_size": [instance_width, instance.get("height")],
                        "underfill": mount_width > 0 and (
                            instance_width < mount_width - 2
                            or max_surface_width > 0 and max_surface_width < mount_width - 2
                        ),
                        "colors": colors,
                        "surfaces": surfaces,
                        "texts": texts,
                    }
                )
            return
        for child in node.get("children", []):
            visit(child)

    visit(root)
    return result


def _rgb(fill_owner: dict[str, Any]) -> tuple[float, float, float] | None:
    for fill in fill_owner.get("fills") or []:
        color = fill.get("color") if isinstance(fill, dict) else None
        if isinstance(color, dict) and fill.get("visible", True) and float(fill.get("opacity", 1) or 0) > 0.5:
            return tuple(float(color.get(c, 0)) for c in ("r", "g", "b"))  # type: ignore[return-value]
    return None


def _luminance(rgb: tuple[float, float, float]) -> float:
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def design_lint(root: dict[str, Any], platform: str) -> dict[str, Any]:
    """Objective quality signals for the designer (advisory, never a hard gate):
    type scale, tiny text, palette size and text contrast against its background."""
    sizes: set[int] = set()
    colors: set[tuple[float, float, float]] = set()
    tiny: list[str] = []
    low_contrast: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], background: tuple[float, float, float] | None) -> None:
        if node.get("visible", True) is False:
            return
        fill = _rgb(node)
        if node.get("type") == "TEXT":
            text = " ".join(str(node.get("characters") or "").split())[:40]
            size = node.get("fontSize") or (node.get("style") or {}).get("fontSize")
            if isinstance(size, int | float):
                sizes.add(round(size))
                if platform == "mobile" and size < 12 and text:
                    tiny.append(text)
            if fill and background and text:
                hi, lo = sorted((_luminance(fill), _luminance(background)), reverse=True)
                ratio = (hi + 0.05) / (lo + 0.05)
                if ratio < 4.5:
                    low_contrast.append({"text": text, "ratio": round(ratio, 2), "id": node.get("id")})
            return
        if fill and node.get("type") != "INSTANCE":
            colors.add(tuple(round(c, 2) for c in fill))  # type: ignore[arg-type]
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                walk(child, fill or background)

    walk(root, _rgb(root) or (1.0, 1.0, 1.0))
    notes = []
    if len(sizes) > 6:
        notes.append(f"{len(sizes)} font sizes {sorted(sizes)}: tighten to a 3-5 step type scale.")
    if tiny:
        notes.append(f"{len(tiny)} text layers below 12px on mobile: {tiny[:4]}")
    if len(colors) > 10:
        notes.append(f"{len(colors)} surface colors: reduce to neutrals + one accent + semantic states.")
    if low_contrast:
        notes.append(f"{len(low_contrast)} text layers below 4.5:1 contrast: {low_contrast[:4]}")
    return {"font_sizes": sorted(sizes), "surface_colors": len(colors), "notes": notes}


async def measure_screen(
    client: Any,
    session: ClientSession,
    *,
    document_id: str,
    page_id: str,
    root_node_id: str,
) -> dict[str, Any]:
    bounds = await client._call(
        session,
        "page_bounds",
        {"document_id": document_id, "page_id": page_id},
    )
    root_bounds = await client._call(
        session,
        "node_bounds",
        {
            "id": root_node_id,
            "document_id": document_id,
            "page_id": page_id,
        },
    )
    placeholders = await client._call(
        session,
        "find_nodes",
        {
            "name": "slot::",
            "document_id": document_id,
            "page_id": page_id,
        },
    )
    overlaps = await client._call(
        session,
        "analyze_overlaps",
        {
            "document_id": document_id,
            "page_id": page_id,
            "severity": "minor",
            "limit": 100,
        },
    )
    root = await client._call(
        session,
        "get_node",
        {
            "id": root_node_id,
            "depth": 8,
            "document_id": document_id,
            "page_id": page_id,
        },
    )
    return {
        "bounds": bounds,
        "root_bounds": root_bounds,
        "placeholders": int(placeholders.get("count", 0)),
        "overlaps": overlaps,
        "root_node_id": root_node_id,
        "small_touch_targets": small_instances(root),
        "clipped_instance_text": clipped_instance_text(root),
        "visible_text": visible_text(root),
        "component_styles": component_styles(root),
        "design_lint": design_lint(root, "mobile" if float(root.get("width") or 0) <= 480 else "desktop"),
    }
