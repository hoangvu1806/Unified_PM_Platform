"""Import a design system from a Figma .fig: tokens → theme CSS, components → HTML snippets.

Components are published component sets (variants) and standalone components on regular
pages; names starting with ``.`` or ``_`` are private by Figma convention and skipped,
as is the internal canvas (library copies used only to resolve instances).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..figio import container
from ..render.document import DEFAULT_THEME
from .convert import Converter
from .scene import Node, Scene, slug
from .tokens import ICON_FONT, Tokens, extract_tokens, theme_css

GOOGLE_FONTS = "https://fonts.googleapis.com/css2?family={}:wght@300;400;500;600;700&display=swap"


@dataclass
class Variant:
    id: str
    component_id: str
    props: dict[str, str]
    width: float
    height: float
    html: str


@dataclass
class ImportedDesignSystem:
    name: str
    theme_css: str
    fonts: list[str]
    tokens: Tokens
    components: list[dict[str, Any]] = field(default_factory=list)
    variants: list[Variant] = field(default_factory=list)

    def index(self) -> dict[str, Any]:
        return {"tokens": self.tokens.summary(), "components": self.components}


def _props(name: str) -> dict[str, str]:
    props = {}
    for part in name.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            props[k.strip()] = v.strip()
    return props


def _private(name: str) -> bool:
    return name.strip().startswith((".", "_"))


def _description(node: Node) -> str:
    text = (node.get("symbolDescription") or node.get("description") or "").strip()
    return re.sub(r"\s+", " ", text)[:300]


def font_urls(families: list[str]) -> list[str]:
    """One Google Fonts stylesheet per text family; families Google lacks just fall back."""
    return [GOOGLE_FONTS.format(f.replace(" ", "+")) for f in families if not ICON_FONT.search(f)][:4]


def import_fig(data: bytes, name: str) -> ImportedDesignSystem:
    fig = container.read_fig(data)
    scene = Scene(fig.message)
    tokens = extract_tokens(scene)
    converter = Converter(scene, tokens)
    result = ImportedDesignSystem(
        name=name, theme_css=theme_css(tokens, DEFAULT_THEME), fonts=font_urls(tokens.fonts), tokens=tokens
    )
    taken: set[str] = set()

    def visible_page(node: Node) -> Node | None:
        page = scene.page(node)
        return None if page is None or page.get("internalOnly") else page

    def add(entry_node: Node, variants: list[Node], set_props: bool) -> None:
        base = slug(entry_node.get("name", ""), "component")
        component_id, i = base, 2
        while component_id in taken:
            component_id, i = f"{base}-{i}", i + 1
        taken.add(component_id)
        props: dict[str, list[str]] = {}
        entries = []
        for v in variants:
            v_props = _props(v.get("name", "")) if set_props else {}
            for k, value in v_props.items():
                props.setdefault(k, [])
                if value not in props[k]:
                    props[k].append(value)
            variant_id = component_id if not v_props else f"{component_id}--{slug('-'.join(v_props.values()), 'v')}"
            while any(e.id == variant_id for e in entries):
                variant_id += "-x"
            size = v.get("size") or {"x": 0, "y": 0}
            entries.append(Variant(variant_id, component_id, v_props, size["x"], size["y"],
                                   converter.component_html(v, entry_node.get("name"))))
        if not entries:
            return
        page = visible_page(entry_node)
        result.components.append({
            "id": component_id,
            "name": entry_node.get("name", component_id),
            "page": (page or {}).get("name", ""),
            "description": _description(entry_node) or _description(variants[0]),
            "props": props,
            "variants": [{"id": e.id, "props": e.props, "width": round(e.width), "height": round(e.height)} for e in entries],
        })
        result.variants.extend(entries)

    for node in scene.of_type("FRAME", "COMPONENT_SET"):
        if node.get("isStateGroup") and not node.get("isSoftDeleted") and not _private(node.get("name", "")) and visible_page(node):
            add(node, [c for c in scene.children(node) if c.get("type") == "SYMBOL" and not c.get("isSoftDeleted")], True)
    for node in scene.of_type("SYMBOL"):
        parent = scene.parent(node)
        if (parent or {}).get("isStateGroup") or node.get("isSoftDeleted") or _private(node.get("name", "")):
            continue
        if visible_page(node):
            add(node, [node], False)
    result.components.sort(key=lambda c: (c["page"], c["name"].lower()))
    return result
