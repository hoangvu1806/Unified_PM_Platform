"""Figma node subtree → HTML + Tailwind (deterministic).

Auto-layout becomes flex (direction, gap, padding, alignment, hug/fixed/fill sizing);
other frames place children absolutely. Fills, strokes, radii, shadows and text styles
use imported tokens when the node references a style or variable, arbitrary values
otherwise. Vectors become inline SVG from Figma's own geometry. Instances inline their
main component with text/fill/visibility overrides applied.
"""

from __future__ import annotations

import html
from typing import Any

from .scene import Key, Node, Scene, hex_color, key
from .tokens import Tokens, font_weight, ref_of, shadow_css

CONTAINERS = {"FRAME", "SYMBOL", "INSTANCE", "SECTION", "GROUP", "COMPONENT", "COMPONENT_SET"}
SHAPES = {"VECTOR", "BOOLEAN_OPERATION", "STAR", "REGULAR_POLYGON"}
HUG = {"RESIZE_TO_FIT", "RESIZE_TO_FIT_WITH_IMPLICIT_SIZE"}
JUSTIFY = {"MIN": "justify-start", "CENTER": "justify-center", "MAX": "justify-end", "SPACE_BETWEEN": "justify-between",
           "SPACE_EVENLY": "justify-evenly", "SPACE_AROUND": "justify-around"}
ITEMS = {"MIN": "items-start", "CENTER": "items-center", "MAX": "items-end", "BASELINE": "items-baseline",
         "STRETCH": "items-stretch"}
TEXT_ALIGN = {"CENTER": "text-center", "RIGHT": "text-right", "JUSTIFIED": "text-justify"}
MAX_DEPTH = 40
MAX_CHARS = 60_000


def px(value: float) -> str:
    return f"{round(value, 2):g}px"


class Converter:
    def __init__(self, scene: Scene, tokens: Tokens) -> None:
        self.scene = scene
        self.tokens = tokens

    # ── public ──
    def component_html(self, node: Node, name: str | None = None) -> str:
        out = self._node(node, None, {}, 0, root=True, component=name or node.get("name", ""))
        return out[:MAX_CHARS]

    # ── colors ──
    def _paint_color(self, paint: dict[str, Any], prefix: str, style: Any = None) -> tuple[list[str], dict[str, str]]:
        """(classes, inline styles) for the top visible paint as background/text/border color."""
        var_ref = ref_of(((paint.get("colorVar") or {}).get("value") or {}).get("alias"))
        token = self.tokens.color_vars.get(var_ref) or (self.tokens.fill_styles.get(style) if style else None)
        if paint.get("type") == "SOLID":
            if token:
                return [f"{prefix}-{token}"], {}
            return [f"{prefix}-[{hex_color(paint['color'], paint.get('opacity', 1.0))}]"], {}
        if paint.get("type", "").startswith("GRADIENT") and paint.get("stops"):
            stops = ", ".join(f"{hex_color(s['color'])} {s.get('position', 0) * 100:g}%" for s in paint["stops"])
            kind = "radial-gradient(circle" if paint["type"] == "GRADIENT_RADIAL" else "linear-gradient(180deg"
            prop = "background-image" if prefix == "bg" else "color"
            return [], {prop: f"{kind}, {stops})"}
        if paint.get("type") == "IMAGE" and prefix == "bg":
            return ["bg-muted"], {}
        return [], {}

    def _top_paint(self, paints: list[dict[str, Any]] | None) -> dict[str, Any] | None:
        visible = [p for p in paints or [] if p.get("visible", True) and p.get("opacity", 1) > 0]
        return visible[-1] if visible else None

    # ── sizing ──
    def _sizing(self, node: Node) -> tuple[str, str]:
        """Own (horizontal, vertical) sizing: fixed | hug."""
        mode = node.get("stackMode")
        if node.get("type") == "TEXT":
            resize = node.get("textAutoResize", "NONE")
            return ("hug" if resize == "WIDTH_AND_HEIGHT" else "fixed", "hug" if resize in {"WIDTH_AND_HEIGHT", "HEIGHT"} else "fixed")
        if mode in {"HORIZONTAL", "VERTICAL"}:
            primary = "hug" if node.get("stackPrimarySizing") in HUG else "fixed"
            counter = "hug" if node.get("stackCounterSizing") in HUG else "fixed"
            return (primary, counter) if mode == "HORIZONTAL" else (counter, primary)
        return ("fixed", "fixed")

    def _layout_classes(self, node: Node, parent: Node | None, root: bool) -> list[str]:
        size = node.get("size") or {"x": 0, "y": 0}
        horizontal, vertical = self._sizing(node)
        classes: list[str] = []
        parent_mode = (parent or {}).get("stackMode")
        in_flow = parent is not None and parent_mode in {"HORIZONTAL", "VERTICAL"} and node.get("stackPositioning") != "ABSOLUTE"
        if parent is not None and not in_flow:
            t = node.get("transform") or {}
            classes += ["absolute", f"left-[{px(t.get('m02', 0))}]", f"top-[{px(t.get('m12', 0))}]"]
        if in_flow:
            grow = node.get("stackChildPrimaryGrow", 0) >= 1
            stretch = node.get("stackChildAlignSelf") == "STRETCH"
            if parent_mode == "HORIZONTAL":
                horizontal = "fill" if grow else horizontal
                vertical = "fill" if stretch else vertical
            else:
                vertical = "fill" if grow else vertical
                horizontal = "fill" if stretch else horizontal
            if horizontal != "fill" and vertical != "fill" and not grow:
                classes.append("shrink-0")
        for axis, mode, length in (("w", horizontal, size["x"]), ("h", vertical, size["y"])):
            if mode == "fixed" and length > 0:
                classes.append(f"{axis}-[{px(length)}]")
            elif mode == "fill":
                primary = (parent_mode == "HORIZONTAL") == (axis == "w")
                classes.append(("flex-1 min-w-0" if axis == "w" else "flex-1 min-h-0") if primary else "self-stretch")
        if root and horizontal == "fixed" and size["x"] > 0:
            classes.append("max-w-full")
        return classes

    def _box_classes(self, node: Node) -> tuple[list[str], dict[str, str]]:
        classes: list[str] = []
        styles: dict[str, str] = {}
        paint = self._top_paint(node.get("fillPaints"))
        if paint and node.get("type") != "TEXT":
            c, s = self._paint_color(paint, "bg", ref_of(node.get("styleIdForFill")))
            classes += c
            styles.update(s)
        stroke = self._top_paint(node.get("strokePaints"))
        weight = node.get("strokeWeight", 0)
        if stroke and weight:
            if node.get("borderStrokeWeightsIndependent"):
                for side, field in (("t", "borderTopWeight"), ("r", "borderRightWeight"), ("b", "borderBottomWeight"), ("l", "borderLeftWeight")):
                    if node.get(field):
                        classes.append(f"border-{side}-[{px(node[field])}]")
            else:
                classes.append("border" if weight == 1 else f"border-[{px(weight)}]")
            c, _ = self._paint_color(stroke, "border", ref_of(node.get("styleIdForStrokeFill")))
            classes += c
            if node.get("dashPattern"):
                classes.append("border-dashed")
        if node.get("rectangleCornerRadiiIndependent"):
            for corner, field in (("tl", "rectangleTopLeftCornerRadius"), ("tr", "rectangleTopRightCornerRadius"),
                                  ("br", "rectangleBottomRightCornerRadius"), ("bl", "rectangleBottomLeftCornerRadius")):
                if node.get(field):
                    classes.append(f"rounded-{corner}-[{px(node[field])}]")
        elif node.get("cornerRadius"):
            radius = node["cornerRadius"]
            size = node.get("size") or {"x": 0, "y": 0}
            classes.append("rounded-full" if radius >= min(size["x"], size["y"]) / 2 > 0 else f"rounded-[{px(radius)}]")
        effect_token = self.tokens.effect_styles.get(ref_of(node.get("styleIdForEffect")))
        if effect_token:
            classes.append(f"shadow-{effect_token}")
        elif node.get("effects"):
            shadow = shadow_css(node["effects"])
            if shadow:
                classes.append(f"shadow-[{shadow.replace(' ', '_')}]")
            if any(e.get("type") == "BACKGROUND_BLUR" and e.get("visible", True) for e in node["effects"]):
                classes.append("backdrop-blur")
        if node.get("opacity", 1) < 1:
            classes.append(f"opacity-[{node['opacity']:.2f}]")
        return classes, styles

    def _flex_classes(self, node: Node) -> list[str]:
        mode = node.get("stackMode")
        if mode not in {"HORIZONTAL", "VERTICAL"}:
            return []
        classes = ["flex"] if mode == "HORIZONTAL" else ["flex", "flex-col"]
        if node.get("stackWrap") == "WRAP":
            classes.append("flex-wrap")
        if node.get("stackSpacing") and node.get("stackPrimaryAlignItems") != "SPACE_BETWEEN":
            classes.append(f"gap-[{px(node['stackSpacing'])}]")
        if node.get("stackWrap") == "WRAP" and node.get("stackCounterSpacing"):
            classes.append(f"gap-y-[{px(node['stackCounterSpacing'])}]")
        top, right = node.get("stackVerticalPadding", 0), node.get("stackPaddingRight", 0)
        bottom, left = node.get("stackPaddingBottom", 0), node.get("stackHorizontalPadding", 0)
        if top == right == bottom == left:
            if top:
                classes.append(f"p-[{px(top)}]")
        else:
            if left == right and left:
                classes.append(f"px-[{px(left)}]")
            else:
                classes += [f"pl-[{px(left)}]"] * bool(left) + [f"pr-[{px(right)}]"] * bool(right)
            if top == bottom and top:
                classes.append(f"py-[{px(top)}]")
            else:
                classes += [f"pt-[{px(top)}]"] * bool(top) + [f"pb-[{px(bottom)}]"] * bool(bottom)
        justify = JUSTIFY.get(node.get("stackPrimaryAlignItems", "MIN"))
        if justify and justify != "justify-start":
            classes.append(justify)
        items = ITEMS.get(node.get("stackCounterAlignItems", "MIN"))
        if items and items != "items-stretch":
            classes.append(items)
        return classes

    # ── nodes ──
    def _node(self, node: Node, parent: Node | None, overrides: dict[Key, dict[str, Any]], depth: int,
              root: bool = False, component: str = "") -> str:
        override = overrides.get(key(node["guid"]), {})
        if not override.get("visible", node.get("visible", True)) or depth > MAX_DEPTH:
            return ""
        node = {**node, **{k: v for k, v in override.items() if k in {"textData", "fillPaints", "strokePaints", "opacity"}}}
        kind = node.get("type")
        layout = self._layout_classes(node, parent, root)
        if kind == "TEXT":
            return self._text(node, layout)
        if kind in SHAPES:
            return self._svg(node, layout)
        box, styles = self._box_classes(node)
        if kind == "ELLIPSE":
            box = [c for c in box if not c.startswith("rounded")] + ["rounded-full"]
        if kind == "LINE":
            stroke = self._top_paint(node.get("strokePaints"))
            color = self._paint_color(stroke, "border")[0] if stroke else ["border-border"]
            return f'<div class="{" ".join(layout + ["border-t"] + color)}"></div>'
        children_html = ""
        flex: list[str] = []
        if kind in CONTAINERS:
            source, child_overrides = node, overrides
            if kind == "INSTANCE":
                main = self.scene.nodes.get(key((node.get("symbolData") or {}).get("symbolID")))
                if main is not None:
                    source = {**main, **{k: v for k, v in node.items() if k not in {"guid", "symbolData"}}}
                    child_overrides = dict(overrides)
                    for item in (node.get("symbolData") or {}).get("symbolOverrides") or []:
                        guids = (item.get("guidPath") or {}).get("guids") or []
                        if guids:
                            child_overrides[key(guids[-1])] = item
                    children = self.scene.children(main)
                else:
                    children = self.scene.children(node)
            else:
                children = self.scene.children(node)
            flex = self._flex_classes(source)
            if source.get("stackMode") not in {"HORIZONTAL", "VERTICAL"} and children:
                flex = ["relative"]
            elif any(c.get("stackPositioning") == "ABSOLUTE" for c in children):
                flex.append("relative")
            if not source.get("frameMaskDisabled", True) and children:
                flex.append("overflow-hidden")
            children_html = "".join(self._node(c, source, child_overrides, depth + 1) for c in children)
        classes = " ".join(dict.fromkeys(layout + flex + box))
        attrs = f' class="{classes}"' if classes else ""
        if styles:
            attrs += f' style="{html.escape("; ".join(f"{k}: {v}" for k, v in styles.items()))}"'
        if root:
            attrs += f' data-component="{html.escape(component)}"'
        tag = "button" if root and "button" in component.lower() else "div"
        return f"<{tag}{attrs}>{children_html}</{tag}>"

    def _text(self, node: Node, layout: list[str]) -> str:
        text = ((node.get("textData") or {}).get("characters") or "").rstrip("\n")
        classes = list(layout)
        token = self.tokens.text_styles.get(ref_of(node.get("styleIdForText")))
        family = (node.get("fontName") or {}).get("family")
        style = (node.get("fontName") or {}).get("style", "Regular")
        if token:
            classes.append(f"text-{token}")
        else:
            classes.append(f"text-[{px(node.get('fontSize', 14))}]")
            weight = font_weight(style)
            if weight != 400:
                classes.append(f"font-[{weight}]")
            lh = node.get("lineHeight") or {}
            if lh.get("units") == "PIXELS":
                classes.append(f"leading-[{px(lh['value'])}]")
            elif lh.get("units") == "PERCENT" and lh.get("value") and lh["value"] != 100:
                classes.append(f"leading-[{lh['value'] / 100:g}]")
        if "italic" in style.lower():
            classes.append("italic")
        paint = self._top_paint(node.get("fillPaints"))
        styles: dict[str, str] = {}
        if paint:
            c, s = self._paint_color(paint, "text", ref_of(node.get("styleIdForFill")))
            classes += c
            styles.update(s)
        align = TEXT_ALIGN.get(node.get("textAlignHorizontal", "LEFT"))
        if align:
            classes.append(align)
        if node.get("textAutoResize") == "WIDTH_AND_HEIGHT":
            classes.append("whitespace-nowrap")
        if node.get("textCase") == "UPPER":
            classes.append("uppercase")
        if node.get("textDecoration") == "UNDERLINE":
            classes.append("underline")
        if family and self.tokens.fonts and family != self.tokens.fonts[0]:
            styles["font-family"] = f"'{family}'"
        attrs = f' class="{" ".join(dict.fromkeys(classes))}"'
        if styles:
            attrs += f' style="{html.escape("; ".join(f"{k}: {v}" for k, v in styles.items()))}"'
        body = "<br>".join(html.escape(line) for line in text.split("\n"))
        return f"<span{attrs}>{body}</span>"

    def _svg(self, node: Node, layout: list[str]) -> str:
        size = node.get("size") or {"x": 0, "y": 0}
        paths = []
        fill = self._top_paint(node.get("fillPaints"))
        stroke = self._top_paint(node.get("strokePaints"))
        for geometry, paint in ((node.get("fillGeometry"), fill), (node.get("strokeGeometry"), stroke)):
            if not geometry or not paint or paint.get("type") != "SOLID":
                continue
            color = hex_color(paint["color"], paint.get("opacity", 1.0))
            for item in geometry:
                d = self.scene.path_data(item.get("commandsBlob", -1))
                if d:
                    rule = ' fill-rule="evenodd"' if item.get("windingRule") == "EVENODD" else ""
                    paths.append(f'<path d="{d}" fill="{color}"{rule}/>')
        if not paths:
            return ""
        w, h = max(size["x"], 1), max(size["y"], 1)
        classes = " ".join(layout + ["overflow-visible"])
        return f'<svg class="{classes}" viewBox="0 0 {w:g} {h:g}" fill="none" aria-hidden="true">{"".join(paths)}</svg>'
