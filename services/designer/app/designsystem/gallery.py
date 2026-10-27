"""Gallery fragment of imported components, for reviewing the conversion on the design page."""

from __future__ import annotations

import html
from typing import Any


def gallery_fragment(components: list[dict[str, Any]], snippets: dict[str, str], title: str) -> str:
    cards = []
    for component in components:
        for variant in component["variants"]:
            snippet = snippets.get(variant["id"])
            if snippet is None:
                continue
            label = component["name"] + (" · " + ", ".join(variant["props"].values()) if variant["props"] else "")
            cards.append(
                '<figure class="flex flex-col gap-2 rounded-lg border border-border bg-background p-3">'
                # Large components are scaled down to fit the card (zoom keeps layout and hit areas).
                f'<div class="flex min-h-16 items-center justify-center overflow-hidden p-2">'
                f'<div style="zoom: {min(1, 250 / max(variant["width"], 1), 320 / max(variant["height"], 1)):.3f}">{snippet}</div></div>'
                f'<figcaption class="truncate text-xs text-muted-foreground" title="{html.escape(label)}">'
                f"{html.escape(label)}<span class=\"ml-1 font-mono\">{html.escape(variant['id'])}</span></figcaption>"
                "</figure>"
            )
    return (
        '<main class="min-h-screen bg-muted p-6">'
        f'<h1 class="mb-4 text-lg font-semibold">{html.escape(title)} — {len(cards)} variants</h1>'
        '<div class="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3">' + "".join(cards) + "</div></main>"
    )
