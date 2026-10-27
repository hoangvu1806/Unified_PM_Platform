"""Design systems at runtime: background import, and the theme a session renders with."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from ..models import DEFAULT_DESIGN_SYSTEM, SessionView
from ..render.document import DEFAULT_FONTS, DEFAULT_THEME
from .importer import import_fig

logger = logging.getLogger("designer_agent.design_systems")


@dataclass
class DesignContext:
    id: str
    name: str
    theme_css: str
    fonts: list[str]
    components: list[dict[str, Any]] = field(default_factory=list)


DEFAULT_CONTEXT = DesignContext(DEFAULT_DESIGN_SYSTEM, "Mặc định (Tailwind + token trung tính)", DEFAULT_THEME, list(DEFAULT_FONTS))


async def design_context(store, session: SessionView | None) -> DesignContext:
    ds_id = (session.design_system_id if session else None) or DEFAULT_DESIGN_SYSTEM
    if ds_id == DEFAULT_DESIGN_SYSTEM:
        # Without an imported design system the session's art direction (palette, fonts, radius) applies.
        theme = (session.visual_theme if session else None) or {}
        if theme.get("css"):
            return DesignContext(DEFAULT_DESIGN_SYSTEM, DEFAULT_CONTEXT.name, DEFAULT_THEME + theme["css"],
                                 theme.get("fonts") or list(DEFAULT_FONTS))
        return DEFAULT_CONTEXT
    ds = await store.get_design_system(ds_id)
    if ds is None or ds.status != "ready":
        return DEFAULT_CONTEXT
    return DesignContext(ds.id, ds.name, ds.theme_css, ds.fonts, ds.components)


async def run_import(store, ds_id: str, data: bytes, name: str) -> None:
    try:
        imported = await asyncio.to_thread(import_fig, data, name)
        await store.finish_design_system(
            ds_id,
            theme_css=imported.theme_css,
            fonts=imported.fonts,
            index=imported.index(),
            snippets=[(v.id, v.component_id, v.html) for v in imported.variants],
        )
        logger.info("Design system %s imported: %d components", ds_id, len(imported.components))
    except Exception as error:  # noqa: BLE001 — reported on the design system row
        logger.exception("Design system %s import failed", ds_id)
        await store.fail_design_system(ds_id, f"{type(error).__name__}: {error}")
