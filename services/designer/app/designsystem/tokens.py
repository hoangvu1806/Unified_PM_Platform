"""Design tokens of a .fig → Tailwind v4 ``@theme``.

Sources: published paint/text/effect styles and local variables (first mode). Every token
gets a namespaced name (``--color-<style>``, ``--text-<style>``, ``--shadow-<style>``,
``--radius-<var>``, ``--spacing-<var>``); the semantic names the agent writes with
(``primary``, ``background``, ``border``, …) are aliased to the best match, falling back to
the default theme.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .scene import Node, Scene, hex_color, key, slug

WEIGHTS = {
    "thin": 100, "hairline": 100, "extralight": 200, "ultralight": 200, "light": 300, "regular": 400,
    "normal": 400, "book": 400, "medium": 500, "semibold": 600, "demibold": 600, "bold": 700,
    "extrabold": 800, "ultrabold": 800, "black": 900, "heavy": 900,
}
ICON_FONT = re.compile(r"awesome|\bicons?\b|symbols|glyph", re.I)
# Semantic name -> name patterns, most specific first.
# Names about text/on-color roles never stand for the fill colors below.
NOT_FILL = re.compile(r"(^|-)(text|on|contrast|foreground|fg)(-|$)")
SEMANTIC: dict[str, list[str]] = {
    "primary": [r"(^|-)primary(-main|-default|-500|-600)?$", r"(^|-)brand(-primary)?(-main|-500)?$", r"primary"],
    "primary-foreground": [r"primary-(contrast-text|foreground|on)$", r"on-primary$"],
    "secondary": [r"(^|-)secondary(-main|-default|-500)?$", r"secondary"],
    "background": [r"(^|-)background(-default)?$", r"(^|-)bg(-default|-primary)?$", r"surface(-default)?$", r"basic-white$"],
    "foreground": [r"text-primary$", r"(^|-)foreground$", r"on-(surface|background)$", r"text(-default)?$", r"basic-black$"],
    "muted": [r"(^|-)muted$", r"background-(paper|secondary|subtle)$", r"surface-(variant|secondary)$", r"grey-100$", r"gray-100$"],
    "muted-foreground": [r"text-secondary$", r"muted-foreground$", r"text-(subtle|muted)$"],
    "card": [r"(^|-)card$", r"background-paper$", r"surface$"],
    "accent": [r"(^|-)accent(-main)?$", r"(^|-)info(-main)?$"],
    "destructive": [r"(^|-)(error|danger|destructive)(-main|-default|-500)?$", r"error|danger|destructive"],
    "success": [r"(^|-)success(-main|-default|-500)?$", r"success"],
    "warning": [r"(^|-)warning(-main|-default|-500)?$", r"warning"],
    "border": [r"(^|-)(border|divider|outline)(-default)?$", r"border|divider|outline"],
}


@dataclass
class Tokens:
    colors: dict[str, str] = field(default_factory=dict)  # slug -> css color
    texts: dict[str, dict[str, Any]] = field(default_factory=dict)  # slug -> {size, line_height, weight, ...}
    shadows: dict[str, str] = field(default_factory=dict)
    radii: dict[str, float] = field(default_factory=dict)
    spacing: dict[str, float] = field(default_factory=dict)
    fonts: list[str] = field(default_factory=list)  # most used first
    semantic: dict[str, str] = field(default_factory=dict)  # semantic name -> color slug
    # References from nodes: style/variable guid or library key -> token slug.
    fill_styles: dict[Any, str] = field(default_factory=dict)
    text_styles: dict[Any, str] = field(default_factory=dict)
    effect_styles: dict[Any, str] = field(default_factory=dict)
    color_vars: dict[Any, str] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "colors": len(self.colors), "texts": len(self.texts), "shadows": len(self.shadows),
            "radii": len(self.radii), "spacing": len(self.spacing), "fonts": self.fonts[:4],
            "semantic": self.semantic,
        }


def _put(store: dict[str, Any], name: str, value: Any) -> str:
    """Add a token; the same name with the same value (library copies) reuses the first."""
    base, i = name, 2
    while name in store and store[name] != value:
        name, i = f"{base}-{i}", i + 1
    store[name] = value
    return name


def _refs(node: Node) -> list[Any]:
    out: list[Any] = [key(node["guid"])]
    if node.get("key"):
        out.append(node["key"])
    return out


def ref_of(style_id: dict[str, Any] | None) -> Any:
    """styleIdFor* / variable alias -> lookup key (local guid or library asset key)."""
    if not style_id:
        return None
    if style_id.get("guid"):
        return key(style_id["guid"])
    asset = style_id.get("assetRef")
    return asset.get("key") if asset else None


def font_weight(style: str) -> int:
    compact = style.lower().replace(" ", "").replace("-", "").replace("italic", "")
    return WEIGHTS.get(compact or "regular", 400)


def shadow_css(effects: list[dict[str, Any]]) -> str:
    parts = []
    for e in effects:
        if not e.get("visible", True) or e.get("type") not in {"DROP_SHADOW", "INNER_SHADOW"}:
            continue
        o = e.get("offset", {"x": 0, "y": 0})
        inset = "inset " if e["type"] == "INNER_SHADOW" else ""
        parts.append(
            f"{inset}{o['x']:g}px {o['y']:g}px {e.get('radius', 0):g}px {e.get('spread', 0):g}px "
            f"{hex_color(e.get('color', {'r': 0, 'g': 0, 'b': 0, 'a': 0.25}))}"
        )
    return ", ".join(parts)


def _live(node: Node) -> bool:
    return not node.get("isSoftDeleted")


def _variable_value(scene: Scene, variable: Node, depth: int = 0) -> Any:
    entries = (variable.get("variableDataValues") or {}).get("entries") or []
    if not entries or depth > 5:
        return None
    value = (entries[0].get("variableData") or {}).get("value") or {}
    if "alias" in value:
        target = scene.nodes.get(ref_of(value["alias"])) if isinstance(ref_of(value["alias"]), tuple) else None
        return _variable_value(scene, target, depth + 1) if target else None
    for k in ("colorValue", "floatValue", "textValue"):
        if k in value:
            return value[k]
    return None


def extract_tokens(scene: Scene) -> Tokens:
    t = Tokens()
    fonts: dict[str, int] = {}
    for node in scene.nodes.values():
        style_type = node.get("styleType")
        if style_type and _live(node):
            name = slug(node.get("name", ""), style_type.lower())
            if style_type == "FILL":
                paints = [p for p in node.get("fillPaints", []) if p.get("visible", True) and p.get("type") == "SOLID"]
                if paints:
                    token = _put(t.colors, name, hex_color(paints[-1]["color"], paints[-1].get("opacity", 1.0)))
                    for ref in _refs(node):
                        t.fill_styles[ref] = token
            elif style_type == "TEXT" and node.get("fontSize"):
                lh = node.get("lineHeight") or {}
                size = node["fontSize"]
                token = _put(t.texts, name, {
                    "size": size,
                    "line_height": lh["value"] if lh.get("units") == "PIXELS" else (
                        lh["value"] / 100 * size if lh.get("units") == "PERCENT" and lh.get("value") else None
                    ),
                    "weight": font_weight(node.get("fontName", {}).get("style", "Regular")),
                    "family": node.get("fontName", {}).get("family"),
                    "tracking": _tracking(node.get("letterSpacing"), size),
                })
                for ref in _refs(node):
                    t.text_styles[ref] = token
            elif style_type == "EFFECT":
                css = shadow_css(node.get("effects", []))
                if css:
                    token = _put(t.shadows, name, css)
                    for ref in _refs(node):
                        t.effect_styles[ref] = token
        if node.get("type") == "VARIABLE":
            value = _variable_value(scene, node)
            parent = scene.nodes.get(ref_of(node.get("variableSetID") or {})) if node.get("variableSetID", {}).get("guid") else None
            name = slug(node.get("name", ""), "var")
            resolved = node.get("variableResolvedType")
            if resolved == "COLOR" and isinstance(value, dict):
                full = name if not parent else slug(f"{parent.get('name', '')}-{node.get('name', '')}")
                token = _put(t.colors, full, hex_color(value))
                for ref in _refs(node):
                    t.color_vars[ref] = token
            elif resolved == "FLOAT" and isinstance(value, (int, float)):
                if re.search(r"radius|corner|rounded", name):
                    _put(t.radii, re.sub(r"^(border-?)?radius-?", "", name) or "base", value)
                elif re.search(r"spacing|space|gap|padding", name):
                    _put(t.spacing, re.sub(r"^(spacing|space)-", "", name), value)
        if node.get("type") == "TEXT" and node.get("fontName") and _live(node):
            family = node["fontName"].get("family")
            if family:
                fonts[family] = fonts.get(family, 0) + 1
    t.fonts = [f for f, _ in sorted(fonts.items(), key=lambda item: -item[1]) if not ICON_FONT.search(f)]
    for semantic, patterns in SEMANTIC.items():
        fill_role = "foreground" not in semantic
        for pattern in patterns:
            match = next((c for c in t.colors if re.search(pattern, c) and not (fill_role and NOT_FILL.search(c))), None)
            if match:
                t.semantic[semantic] = match
                break
    return t


def _tracking(spacing: dict[str, Any] | None, size: float) -> float | None:
    if not spacing or not spacing.get("value"):
        return None
    return spacing["value"] if spacing.get("units") == "PIXELS" else spacing["value"] / 100 * size


def theme_css(tokens: Tokens, default_theme: str) -> str:
    """Default theme first (complete semantic set), then this system's tokens and aliases."""
    lines = []
    if tokens.fonts:
        lines.append(f'  --font-sans: "{tokens.fonts[0]}", ui-sans-serif, system-ui, sans-serif;')
        for family in tokens.fonts[1:4]:
            lines.append(f'  --font-{slug(family)}: "{family}", ui-sans-serif, system-ui, sans-serif;')
    lines += [f"  --color-{k}: {v};" for k, v in tokens.colors.items()]
    lines += [f"  --color-{k}: var(--color-{v});" for k, v in tokens.semantic.items() if k != v]
    for k, v in tokens.texts.items():
        lines.append(f"  --text-{k}: {v['size']:g}px;")
        if v.get("line_height"):
            lines.append(f"  --text-{k}--line-height: {v['line_height']:g}px;")
        lines.append(f"  --text-{k}--font-weight: {v['weight']};")
        if v.get("tracking"):
            lines.append(f"  --text-{k}--letter-spacing: {v['tracking']:.3g}px;")
    lines += [f"  --shadow-{k}: {v};" for k, v in tokens.shadows.items()]
    lines += [f"  --radius-{k}: {v:g}px;" for k, v in tokens.radii.items()]
    lines += [f"  --spacing-{k}: {v:g}px;" for k, v in tokens.spacing.items()]
    return default_theme.rstrip() + "\n\n/* Imported design system */\n@theme {\n" + "\n".join(lines) + "\n}\n"
