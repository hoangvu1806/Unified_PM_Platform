"""Art direction of a session → Tailwind ``@theme`` overrides and Google Fonts links.

Used when the session has no imported design system: the spec's palette, font pair and
radius become the theme every screen renders with (iframe, checks and exports alike).
"""

from __future__ import annotations

from typing import Any

from .importer import font_urls

RADIUS = {"none": 0, "sm": 4, "md": 6, "lg": 8, "xl": 12, "2xl": 16}


def direction_theme(direction: dict[str, Any]) -> dict[str, Any] | None:
    """{"css": "@theme {...}", "fonts": [urls]} or None when there is nothing to apply."""
    palette = direction.get("palette") or {}
    heading = (direction.get("heading_font") or "").strip()
    body = (direction.get("body_font") or "").strip()
    lines = []
    if palette:
        p = palette.get
        tokens = {
            "primary": p("primary"), "primary-foreground": p("primary_foreground"),
            "background": p("background"), "foreground": p("foreground"),
            "card": p("surface"), "card-foreground": p("foreground"),
            "secondary": p("muted"), "secondary-foreground": p("foreground"),
            "muted": p("muted"), "muted-foreground": p("muted_foreground"),
            "accent": p("accent"), "accent-foreground": p("foreground"),
            "border": p("border"), "input": p("border"), "ring": p("primary"),
            "success": p("success"), "warning": p("warning"), "destructive": p("destructive"),
        }
        lines += [f"  --color-{k}: {v};" for k, v in tokens.items() if v]
    if body:
        lines.append(f'  --font-sans: "{body}", ui-sans-serif, system-ui, sans-serif;')
    if heading:
        lines.append(f'  --font-heading: "{heading}", "{body or heading}", ui-sans-serif, system-ui, sans-serif;')
    base = RADIUS.get(direction.get("radius") or "lg", 8)
    lines += [f"  --radius-sm: {max(base // 2, 0)}px;", f"  --radius-md: {round(base * 0.75)}px;",
              f"  --radius-lg: {base}px;", f"  --radius-xl: {round(base * 1.5)}px;", f"  --radius-2xl: {base * 2}px;"]
    if not lines:
        return None
    families = list(dict.fromkeys(f for f in (body, heading) if f))
    return {"css": "\n/* Art direction */\n@theme {\n" + "\n".join(lines) + "\n}\n", "fonts": font_urls(families)}
