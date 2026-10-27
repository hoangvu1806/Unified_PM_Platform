"""Export the screens of a session: Figma .fig, PNG per screen/state, offline HTML prototype (zip)."""

from __future__ import annotations

import html
import io
import json
import zipfile
from dataclasses import dataclass, field

from ..designsystem.service import DesignContext
from ..models import ScreenView
from ..render.document import RUNTIME_JS, VENDOR_DIR, fragment_of
from ..render.assets import inline_assets
from .figma import CapturedScreen, build_fig, capture

MAX_STATES = 4
NAV_JS = """document.addEventListener("click", (e) => {
  const link = e.target.closest("[data-goto]");
  if (link) { e.preventDefault(); location.href = link.getAttribute("data-goto") + ".html"; }
});
window.addEventListener("hashchange", () => document.documentElement.setAttribute("data-active-state", location.hash.slice(1)));
if (location.hash) document.documentElement.setAttribute("data-active-state", location.hash.slice(1));"""


@dataclass
class Export:
    fig: bytes = b""
    zip: bytes = b""
    pngs: dict[str, bytes] = field(default_factory=dict)  # "<screen>[--<state>].png" -> bytes


def _standalone(screen: ScreenView, body: str, css: str, fonts: list[str]) -> str:
    links = "".join(f'<link rel="stylesheet" href="{html.escape(u)}">' for u in fonts)
    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(screen.name)}</title>
{links}
<style>{css}</style>
<script src="../assets/lucide.min.js"></script>
<script defer src="../assets/alpine.min.js"></script>
<script>{RUNTIME_JS}</script>
<script>{NAV_JS}</script>
</head>
<body class="antialiased">
{body}
</body>
</html>
"""


def _index(title: str, screens: list[ScreenView], states: dict[str, list[str]]) -> str:
    items = "".join(
        f'<li><a href="screens/{s.id}.html"><img src="png/{s.id}.png" alt=""><b>{html.escape(s.name)}</b></a>'
        + "".join(f' <a class="state" href="screens/{s.id}.html#{st}">{html.escape(st)}</a>' for st in states.get(s.id, []))
        + "</li>"
        for s in screens
    )
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font:14px system-ui;margin:32px;background:#f4f4f5}}ul{{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}}
li{{background:#fff;border:1px solid #e4e4e7;border-radius:12px;padding:12px}}img{{width:100%;height:180px;object-fit:cover;object-position:top;border-radius:8px;display:block;margin-bottom:8px}}
a{{color:#18181b;text-decoration:none}}.state{{font-size:12px;color:#6366f1;margin-right:6px}}</style></head>
<body><h1>{html.escape(title)}</h1><p>design.fig: kéo vào Figma · png/: ảnh từng màn hình và trạng thái</p><ul>{items}</ul></body></html>"""


async def export_screens(renderer, screens: list[ScreenView], design: DesignContext, title: str,
                         project_id: str | None = None) -> Export:
    out = Export()
    captured: list[CapturedScreen] = []
    states: dict[str, list[str]] = {}
    files: dict[str, bytes] = {}
    for screen in screens:
        body = await inline_assets(fragment_of(screen.html or ""), project_id)
        base = await renderer.render(body, width=screen.width, theme_css=design.theme_css, fonts=design.fonts,
                                     screenshot="png", lint=False, max_height=16000)
        out.pngs[f"{screen.id}.png"] = base.image
        states[screen.id] = base.states[:MAX_STATES]
        files[f"screens/{screen.id}.html"] = _standalone(screen, body, base.css, design.fonts).encode("utf-8")
        captured.append(await capture(renderer, body, name=screen.name, width=screen.width,
                                      theme_css=design.theme_css, fonts=design.fonts))
        for state in states[screen.id]:
            shot = await renderer.render(body, width=screen.width, theme_css=design.theme_css, fonts=design.fonts,
                                         state=state, screenshot="png", lint=False, max_height=16000)
            out.pngs[f"{screen.id}--{state}.png"] = shot.image
            captured.append(await capture(renderer, body, name=f"{screen.name} · {state}", width=screen.width,
                                          theme_css=design.theme_css, fonts=design.fonts, state=state))
    out.fig = build_fig(captured, title)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("index.html", _index(title, screens, states))
        z.writestr("design.fig", out.fig, zipfile.ZIP_STORED)
        for name, data in out.pngs.items():
            z.writestr(f"png/{name}", data, zipfile.ZIP_STORED)
        for name, data in files.items():
            z.writestr(name, data)
        for vendor in ("alpine.min.js", "lucide.min.js"):
            z.write(VENDOR_DIR / vendor, f"assets/{vendor}")
        z.writestr("screens.json", json.dumps([{"id": s.id, "name": s.name, "platform": s.platform, "version": s.version,
                                                "states": states.get(s.id, [])} for s in screens], ensure_ascii=False, indent=2))
    out.zip = buf.getvalue()
    return out
