"""Headless Chromium (Playwright) rendering of one screen: screenshot, DOM lint, compiled CSS.

One browser per process, started on first use; every render gets its own context so
viewport, state and storage never leak between screens. Vendor scripts are served from
disk through ``page.route``; other requests are limited to fonts and https images
(``allow_network``) and aborted otherwise.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from playwright.async_api import Browser, Page, Playwright, Route, async_playwright

from .document import VENDOR_DIR, build_document

logger = logging.getLogger("designer_agent.render")

VENDOR_ORIGIN = "https://designer.render"
VENDOR_BASE = f"{VENDOR_ORIGIN}/vendor/"
SCREEN_URL = f"{VENDOR_ORIGIN}/screen"
LINT_JS = (Path(__file__).resolve().parent / "lint.js").read_text(encoding="utf-8")
FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
# Tailwind's browser build compiles asynchronously; body carries "antialiased", so its
# rule appearing in a generated <style> means the first compile has landed.
READY_JS = """() => window.__designer && [...document.querySelectorAll('style')]
  .some(s => s.textContent.includes('-webkit-font-smoothing'))"""
CSS_JS = """() => [...document.querySelectorAll('style:not([type]):not(#designer-states)')]
  .map(s => s.textContent).filter(t => t.includes('tailwindcss')).join('\\n')"""


@dataclass
class RenderResult:
    width: int
    height: int
    image: bytes | None = None
    mime: str | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    css: str = ""
    states: list[str] = field(default_factory=list)
    console: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[dict[str, Any]]:
        return [f for f in self.findings if f["severity"] == "error"]


class Renderer:
    def __init__(self, *, allow_network: bool = True, timeout_ms: int = 15_000) -> None:
        self.allow_network = allow_network
        self.timeout_ms = timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> Browser:
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(args=["--disable-dev-shm-usage"])
            return self._browser

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    async def _route(self, route: Route, document: str) -> None:
        url = route.request.url
        if url == SCREEN_URL:
            await route.fulfill(body=document, content_type="text/html; charset=utf-8")
            return
        if url.startswith(VENDOR_BASE):
            path = (VENDOR_DIR / url[len(VENDOR_BASE) :].split("?", 1)[0]).resolve()
            if path.parent == VENDOR_DIR and path.is_file():
                await route.fulfill(path=str(path), content_type="text/javascript")
                return
            await route.abort()
            return
        host = url.split("/", 3)[2] if "://" in url else ""
        if self.allow_network and url.startswith("https://") and (
            host in FONT_HOSTS or route.request.resource_type in {"image", "media"}
        ):
            await route.continue_()
            return
        await route.abort()

    @asynccontextmanager
    async def page(
        self,
        fragment: str,
        *,
        width: int,
        height: int = 900,
        theme_css: str | None = None,
        fonts: list[str] | None = None,
        state: str | None = None,
        scale: float = 1,
        axe: bool = False,
        console: list[str] | None = None,
    ) -> AsyncIterator[Page]:
        """A page with the screen loaded, Tailwind compiled, fonts loaded and ``state`` applied."""
        browser = await self._ensure()
        extra = {"fonts": fonts} if fonts is not None else {}
        document = build_document(fragment, vendor_base=VENDOR_BASE, theme_css=theme_css, axe=axe, **extra)
        context = await browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=scale)
        try:
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)
            if console is not None:
                page.on("console", lambda m: console.append(f"{m.type}: {m.text}") if m.type in {"error", "warning"} else None)
                page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
            # A real navigation (not set_content/document.write) so scripts load normally and
            # the CSP applies to a proper origin.
            await page.route("**/*", lambda route: self._route(route, document))
            await page.goto(SCREEN_URL, wait_until="load")
            await page.wait_for_function(READY_JS)
            if state:
                await page.evaluate("s => document.documentElement.setAttribute('data-active-state', s)", state)
            await page.evaluate("() => document.fonts.ready")
            await page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
            yield page
        finally:
            await context.close()

    async def render(
        self,
        fragment: str,
        *,
        width: int,
        height: int = 900,
        theme_css: str | None = None,
        fonts: list[str] | None = None,
        state: str | None = None,
        screenshot: Literal["jpeg", "png"] | None = "jpeg",
        scale: float = 1,
        lint: bool = True,
        axe: bool = True,
        max_height: int = 6000,
    ) -> RenderResult:
        console: list[str] = []
        async with self.page(
            fragment, width=width, height=height, theme_css=theme_css, fonts=fonts, state=state, scale=scale,
            axe=lint and axe, console=console,
        ) as page:
            result = RenderResult(width=width, height=height, console=console)
            result.states = await page.evaluate("() => window.__designer.states")
            result.css = await page.evaluate(CSS_JS)
            if lint:
                report = await page.evaluate(LINT_JS, {"mobile": width <= 480, "axe": axe})
                result.findings, result.text, result.height = report["findings"], report["text"], report["height"]
            else:
                result.text = await page.evaluate("() => document.body.innerText")
                result.height = await page.evaluate("() => document.documentElement.scrollHeight")
            if screenshot:
                clip = {"x": 0, "y": 0, "width": width, "height": min(result.height, max_height)}
                options: dict[str, Any] = {"type": screenshot, "clip": clip, "full_page": True}
                if screenshot == "jpeg":
                    options["quality"] = 72
                result.image = await page.screenshot(**options)
                result.mime = f"image/{screenshot}"
            return result
