"""Deterministic visualization of the LLM-authored project color system."""

import html

from ..models import StyleManifest


def get_color_tokens(style: StyleManifest) -> list[tuple[str, str, str, str]]:
    """Expose only colors present in the project StyleManifest."""
    return [
        ("brand/primary", style.primary_color, "Brand Primary", "Primary actions and identity"),
        ("brand/primary-dark", style.primary_dark, "Brand Active", "Active and emphasis states"),
        ("accent/color", style.accent_color, "Accent", "Highlights and selected details"),
        ("neutral/dark", style.neutral_dark, "Primary Ink", "Headings and high contrast text"),
        ("neutral/body", style.neutral_body, "Body Ink", "Body copy and secondary text"),
        ("neutral/border", style.border_color, "Border", "Dividers and component outlines"),
        ("neutral/canvas", style.canvas_background, "Canvas", "Application background"),
        ("surface/card", style.surface_card, "Surface", "Cards, panels, and overlays"),
        ("status/success", style.success_color, "Success", "Positive and confirmed states"),
        ("status/warning", style.warning_color, "Warning", "Attention and pending states"),
        ("status/danger", style.danger_color, "Danger", "Errors and destructive states"),
        ("status/info", style.info_color, "Information", "Guidance and informational states"),
    ]


def _safe(value: object) -> str:
    return html.escape(str(value), quote=True).replace("{", "&#123;").replace("}", "&#125;")


def compile_palette_jsx(screen_name: str, style: StyleManifest) -> str:
    """Render authored tokens without introducing new palette decisions."""
    cards = []
    for token_name, value, label, purpose in get_color_tokens(style):
        cards.append(
            f'    <Frame name="{_safe(token_name)}" w={{220}} p={{16}} '
            f'bg="{style.surface_card}" stroke="{style.border_color}" strokeWidth={{1}} '
            f'rounded={{{style.corner_radius}}} flex="col" gap={{10}}>\n'
            f'      <Rectangle name="{_safe(label)} Swatch" w="fill" h={{88}} '
            f'rounded={{{max(0, style.corner_radius - 2)}}} fill="{value}" />\n'
            f'      <Text size={{14}} weight="bold" color="{style.neutral_dark}">{_safe(label)}</Text>\n'
            f'      <Text size={{12}} color="{style.neutral_body}">{_safe(value)}</Text>\n'
            f'      <Text size={{11}} color="{style.neutral_body}">{_safe(purpose)}</Text>\n'
            "    </Frame>"
        )
    return (
        f'<Frame name="Color System" w={{1440}} h="hug" p={{64}} '
        f'bg="{style.canvas_background}" flex="col" gap={{32}}>\n'
        f'  <Text size={{34}} weight="bold" color="{style.neutral_dark}">'
        f'{_safe(screen_name)} — Color System</Text>\n'
        f'  <Frame name="LLM Authored Tokens" w="fill" flex="row" wrap={{true}} gap={{16}}>\n'
        + "\n".join(cards)
        + "\n  </Frame>\n</Frame>"
    )
