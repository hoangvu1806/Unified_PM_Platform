"""Rendered screens → Figma .fig (via figio.FigBuilder).

Each element becomes a frame at its rendered position (Figma does not re-run auto-layout
on open), flex containers keep auto-layout settings so the design reflows when edited,
text keeps its font, and svg/img/canvas become image fills screenshotted from Chromium.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..figio.writer import FigBuilder, drop_shadow, solid

EXTRACT_JS = (Path(__file__).resolve().parent / "extract.js").read_text(encoding="utf-8")
SHOT_SCALE = 2
GAP = 160
# Figma's style names (with spaces): a name the font does not have leaves the text unrendered.
WEIGHT_STYLE = {100: "Thin", 200: "Extra Light", 300: "Light", 400: "Regular", 500: "Medium", 600: "Semi Bold",
                700: "Bold", 800: "Extra Bold", 900: "Black"}
JUSTIFY = {"center": "CENTER", "flex-end": "MAX", "end": "MAX", "right": "MAX", "space-between": "SPACE_BETWEEN",
           "space-around": "SPACE_AROUND", "space-evenly": "SPACE_EVENLY"}
ALIGN = {"center": "CENTER", "flex-end": "MAX", "end": "MAX", "baseline": "BASELINE"}


@dataclass
class CapturedScreen:
    name: str
    tree: dict[str, Any]
    shots: dict[str, bytes]


def hexa(rgba: list[float] | None) -> str | None:
    if not rgba:
        return None
    r, g, b, a = rgba
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}" + ("" if a >= 0.999 else f"{round(a * 255):02x}")


async def capture(renderer, fragment: str, *, name: str, width: int, theme_css: str | None, fonts: list[str] | None,
                  state: str | None = None) -> CapturedScreen:
    async with renderer.page(fragment, width=width, theme_css=theme_css, fonts=fonts, state=state,
                             scale=SHOT_SCALE) as page:
        tree = await page.evaluate(EXTRACT_JS)
        shots: dict[str, bytes] = {}
        for element in await page.query_selector_all("[data-shot]"):
            shot = await element.get_attribute("data-shot")
            try:
                shots[shot] = await element.screenshot(type="png", omit_background=True)
            except Exception:  # noqa: BLE001 — an element that cannot be captured is left out
                continue
    return CapturedScreen(name, tree, shots)


class _Writer:
    def __init__(self, builder: FigBuilder) -> None:
        self.b = builder

    def layer(self, parent, layer: dict[str, Any], origin: tuple[float, float], parent_layer: dict[str, Any] | None,
              shots: dict[str, bytes]) -> None:
        x, y = layer["x"] - origin[0], layer["y"] - origin[1]
        w, h = max(layer["w"], 0.01), max(layer["h"], 0.01)
        child_of_flex = bool(parent_layer and (parent_layer.get("box") or {}).get("flex"))
        extra: dict[str, Any] = {}
        if child_of_flex:
            if layer.get("absolute"):
                extra["stackPositioning"] = "ABSOLUTE"
            if layer.get("grow"):
                extra["stackChildPrimaryGrow"] = 1.0
            if layer.get("stretch"):
                extra["stackChildAlignSelf"] = "STRETCH"
        kind = layer["kind"]
        if kind == "text":
            self.text(parent, layer, x, y, w, h, extra)
            return
        if kind == "raster":
            data = shots.get(layer.get("shot", ""))
            if data:
                paint = self.b.image_paint(data, round(w * SHOT_SCALE), round(h * SHOT_SCALE), "FIT")
                self.b.rect(parent, layer["name"], x, y, w, h, fillPaints=[paint], **extra)
            return
        box = layer.get("box") or {}
        children = layer.get("children") or []
        if self._transparent(box) and len(children) == 1 and not box.get("flex") and not layer.get("root"):
            only = children[0]
            if abs(only["x"] - layer["x"]) < 0.5 and abs(only["y"] - layer["y"]) < 0.5 and abs(only["w"] - w) < 0.5:
                self.layer(parent, only, origin, parent_layer, shots)
                return
        if not children and self._transparent(box):
            return
        frame = self.b.frame(parent, layer["name"][:80], x, y, w, h, clip=bool(box.get("clip")),
                             layout=self._layout(box), **{**extra, **self._paint(box, w, h)})
        # CSS paints positioned (absolute/fixed) children above in-flow ones; Figma paints later children on top.
        for child in sorted(children, key=lambda c: bool(c.get("absolute"))):
            self.layer(frame, child, (layer["x"], layer["y"]), layer, shots)

    @staticmethod
    def _transparent(box: dict[str, Any]) -> bool:
        return not box.get("bg") and not any(b["w"] and b["c"] for b in box.get("border", [])) and not box.get("shadows")

    @staticmethod
    def _layout(box: dict[str, Any]) -> dict[str, Any] | None:
        flex = box.get("flex")
        if not flex:
            return None
        return {
            "mode": flex["dir"], "gap": flex["gap"], "padding": tuple(flex["pad"]),
            "align": JUSTIFY.get(flex["justify"], "MIN"), "cross": ALIGN.get(flex["align"], "MIN"),
        }

    def _paint(self, box: dict[str, Any], w: float, h: float) -> dict[str, Any]:
        fields: dict[str, Any] = {"fillPaints": [solid(hexa(box["bg"]))] if box.get("bg") else []}
        borders = [b for b in box.get("border", []) if b["w"] and b["c"]]
        if borders:
            fields["strokePaints"] = [solid(hexa(borders[0]["c"]))]
            weights = [b["w"] if b["c"] else 0 for b in box["border"]]
            if len(set(weights)) == 1:
                fields["strokeWeight"] = float(weights[0])
            else:
                fields.update(strokeWeight=float(max(weights)), borderStrokeWeightsIndependent=True,
                              borderTopWeight=float(weights[0]), borderRightWeight=float(weights[1]),
                              borderBottomWeight=float(weights[2]), borderLeftWeight=float(weights[3]))
            fields["strokeAlign"] = "INSIDE"
        radius = [min(r, w / 2, h / 2) for r in box.get("radius", [0, 0, 0, 0])]
        if any(radius):
            if len(set(radius)) == 1:
                fields["cornerRadius"] = float(radius[0])
            else:
                fields.update(rectangleCornerRadiiIndependent=True, rectangleTopLeftCornerRadius=float(radius[0]),
                              rectangleTopRightCornerRadius=float(radius[1]),
                              rectangleBottomRightCornerRadius=float(radius[2]),
                              rectangleBottomLeftCornerRadius=float(radius[3]))
        effects = []
        for s in box.get("shadows", []):
            effect = drop_shadow(hexa(s["color"]), s["x"], s["y"], s["blur"], s["spread"])
            if s.get("inset"):
                effect["type"] = "INNER_SHADOW"
            effects.append(effect)
        if effects:
            fields["effects"] = effects
        if box.get("opacity", 1) < 1:
            fields["opacity"] = float(box["opacity"])
        return fields

    def text(self, parent, layer: dict[str, Any], x: float, y: float, w: float, h: float, extra: dict[str, Any]) -> None:
        st = layer["style"]
        text = layer["text"]
        if st.get("transform") == "uppercase":
            text = text.upper()
        weight = min(WEIGHT_STYLE, key=lambda k: abs(k - st.get("weight", 400)))
        style = ("Italic" if weight == 400 else WEIGHT_STYLE[weight] + " Italic") if st.get("italic") else WEIGHT_STYLE[weight]
        fields = {
            "textAlignHorizontal": {"center": "CENTER", "right": "RIGHT", "end": "RIGHT", "justify": "JUSTIFIED"}.get(
                st.get("align"), "LEFT"),
        }
        if st.get("letterSpacing"):
            fields["letterSpacing"] = {"value": float(st["letterSpacing"]), "units": "PIXELS"}
        if st.get("decoration") and "underline" in st["decoration"]:
            fields["textDecoration"] = "UNDERLINE"
        # Lines are already broken as the browser rendered them: Figma only sizes the box, never re-wraps.
        self.b.text(
            parent, text, x, y, w + 1, h, size=st["size"], family=st["family"] or "Inter",
            style=style, fill=hexa(st["color"]) or "#000000", line_height=st.get("lineHeight"),
            auto_resize="WIDTH_AND_HEIGHT", **fields, **extra,
        )


def build_fig(screens: list[CapturedScreen], file_name: str, columns: list[int] | None = None) -> bytes:
    """``columns``: column index per screen (states of one screen share a column, stacked)."""
    b = FigBuilder(file_name)
    page = b.page("Screens")
    writer = _Writer(b)
    column_x: dict[int, float] = {}
    column_y: dict[int, float] = {}
    next_x = 0.0
    for i, screen in enumerate(screens):
        col = columns[i] if columns else i
        if col not in column_x:
            column_x[col], column_y[col] = next_x, 0.0
            next_x += screen.tree["w"] + GAP
        tree = {**screen.tree, "name": screen.name, "root": True}
        tree.setdefault("box", {})
        if not tree["box"].get("bg"):
            tree["box"]["bg"] = [255, 255, 255, 1]
        origin = (tree["x"] - column_x[col], tree["y"] - column_y[col])
        writer.layer(page, tree, origin, None, screen.shots)
        column_y[col] += tree["h"] + GAP
    return b.to_bytes()
