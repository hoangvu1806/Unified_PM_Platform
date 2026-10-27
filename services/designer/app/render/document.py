"""One screen = an HTML body fragment; this wraps it into the document that the design
iframe and headless Chromium both load: theme tokens, Tailwind (browser build), Alpine,
the designer runtime and a CSP that blocks network access except vendor files, fonts
and images.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
VENDOR_DIR = HERE / "vendor"
DEFAULT_THEME = (HERE / "default_theme.css").read_text(encoding="utf-8")
RUNTIME_JS = (HERE / "runtime.js").read_text(encoding="utf-8")
FONTS_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"

_BODY = re.compile(r"<body[^>]*>(.*?)</body>", re.S | re.I)
_HEAD_STYLES = re.compile(r"<head[^>]*>.*?</head>", re.S | re.I)
_STYLE = re.compile(r"<style[^>]*>.*?</style>", re.S | re.I)


def fragment_of(markup: str) -> str:
    """Accept a body fragment or a whole document (keeps <style> blocks from its head)."""
    body = _BODY.search(markup)
    if not body:
        return markup.strip()
    head = _HEAD_STYLES.search(markup)
    styles = "\n".join(_STYLE.findall(head.group(0))) if head else ""
    return (styles + "\n" + body.group(1)).strip()


def build_document(
    fragment: str,
    *,
    vendor_base: str,
    theme_css: str | None = None,
    title: str = "Screen",
    fonts_url: str | None = FONTS_URL,
    axe: bool = False,
) -> str:
    """``vendor_base``: absolute URL ending in ``/`` where ``vendor/*.js`` are served."""
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(vendor_base))
    csp = "; ".join(
        [
            "default-src 'none'",
            # Alpine evaluates its expressions with new Function.
            f"script-src {origin} 'unsafe-inline' 'unsafe-eval'",
            "style-src 'unsafe-inline' https://fonts.googleapis.com",
            "font-src https://fonts.gstatic.com data:",
            "img-src data: blob: https:",
            "media-src data: blob: https:",
        ]
    )
    scripts = [f'<script src="{vendor_base}tailwindcss-browser.js"></script>']
    if axe:
        scripts.append(f'<script src="{vendor_base}axe.min.js"></script>')
    fonts = f'<link rel="stylesheet" href="{html.escape(fonts_url)}">' if fonts_url else ""
    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>{html.escape(title)}</title>
{fonts}
<style type="text/tailwindcss">
{theme_css or DEFAULT_THEME}
@layer base {{
  html, body {{ background: var(--color-background); color: var(--color-foreground); font-family: var(--font-sans); }}
  [x-cloak] {{ display: none !important; }}
}}
</style>
{"".join(scripts)}
<script defer src="{vendor_base}alpine.min.js"></script>
<script>{RUNTIME_JS}</script>
</head>
<body class="antialiased">
{fragment_of(fragment)}
</body>
</html>
"""
