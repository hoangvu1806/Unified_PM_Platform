"""Tools of the screen builder (ADK function tools) and the completion gate.

Every write/edit saves a new screen version and returns the DOM lint report, so the model
sees problems without an extra call; ``check_screen`` adds a screenshot to the next model
turn (it is not kept in the conversation, which keeps prompts small).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from uuid import UUID

from google.adk.tools import ToolContext
from google.genai import types

from ..designsystem.service import DesignContext
from ..models import ScreenWrite
from ..render import fragment_of
from ..render.assets import inline_assets
from ..render.images import find_images as search_images
from .schemas import ScreenSpec

MAX_FINDINGS = 8
SNIPPET_LIMIT = 6000
KEEP_ARG_CHARS = 400


def _clip_arg(value: Any) -> Any:
    if isinstance(value, str) and len(value) > KEEP_ARG_CHARS:
        return value[:160] + f" … [{len(value)} chars]"
    return value


def compact_history(contents: list[types.Content]) -> list[types.Content]:
    """Drop bulky HTML from earlier turns: the screen lives in the store, read_screen returns it.

    Every model call resends the conversation, so a 40k-character write_screen argument would be
    paid again on each later call. Written HTML becomes a one-line marker, long edit snippets are
    clipped, and only the latest read_screen/get_component result keeps its HTML, until a later
    write/edit makes it stale.
    """
    last_read = None
    for ci, content in enumerate(contents):
        for pi, part in enumerate(content.parts or []):
            response, call = part.function_response, part.function_call
            if response is not None and response.name in {"read_screen", "get_component"}:
                last_read = (ci, pi)
            elif call is not None and call.name in {"write_screen", "edit_screen"} and last_read and last_read[1] >= 0:
                # A later change makes that HTML stale: keep a read only until the screen changes.
                last_read = (-1, -1)
    out = []
    for ci, content in enumerate(contents):
        parts, changed = [], False
        for pi, part in enumerate(content.parts or []):
            call, response = part.function_call, part.function_response
            if call is not None and call.name in {"write_screen", "edit_screen"} and call.args:
                args = {k: _clip_arg(v) for k, v in call.args.items()}
                if call.name == "write_screen" and "html" in call.args:
                    args["html"] = f"[{len(call.args['html'])} chars of HTML, saved; read_screen returns the current HTML]"
                if args != call.args:
                    part = types.Part(function_call=types.FunctionCall(id=call.id, name=call.name, args=args))
                    changed = True
            elif (response is not None and response.name in {"read_screen", "get_component"}
                  and (ci, pi) != last_read and isinstance(response.response, dict) and "html" in response.response):
                compact = {**response.response, "html": "[superseded: call read_screen again for the current HTML]"}
                part = types.Part(function_response=types.FunctionResponse(id=response.id, name=response.name, response=compact))
                changed = True
            parts.append(part)
        out.append(types.Content(role=content.role, parts=parts) if changed else content)
    return out


def _report(result) -> dict[str, Any]:
    findings = [
        {
            "severity": f["severity"],
            "rule": f["rule"],
            "message": f["message"],
            "elements": [{"text": e["text"], "html": e["html"]} for e in f["elements"][:3]],
        }
        for f in sorted(result.findings, key=lambda f: {"error": 0, "warning": 1, "info": 2}[f["severity"]])[:MAX_FINDINGS]
    ]
    return {
        "errors": sum(1 for f in result.findings if f["severity"] == "error"),
        "warnings": sum(1 for f in result.findings if f["severity"] == "warning"),
        "findings": findings,
        "page_height": result.height,
        "states": result.states,
        "console_errors": [c for c in result.console if c.startswith(("error", "pageerror"))][:5],
    }


@dataclass
class BuildState:
    version: int = 0
    checked_version: int = -1
    screenshot_version: int = -1
    blocking: int = 0
    finished: bool = False
    summary: str = ""
    steps: int = 0
    pending_image: list[types.Part] = field(default_factory=list)


class ScreenTools:
    def __init__(
        self,
        *,
        store,
        renderer,
        session_id: UUID,
        run_id: UUID,
        screen: ScreenSpec,
        design: DesignContext,
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
        user: str | None,
        unsplash_key: str = "",
    ) -> None:
        self.store = store
        self.renderer = renderer
        self.session_id = session_id
        self.run_id = run_id
        self.screen = screen
        self.design = design
        self.emit = emit
        self.user = user
        self.unsplash_key = unsplash_key
        self.state = BuildState()
        self.width = {"mobile": 390, "tablet": 834}.get(screen.platform, 1440)

    async def _current(self) -> str:
        saved = await self.store.get_screen(self.session_id, self.screen.id)
        return saved.html if saved else ""

    async def _render(self, html: str, *, state: str | None = None, screenshot: bool = False):
        return await self.renderer.render(
            await inline_assets(html), width=self.width, state=state, theme_css=self.design.theme_css,
            fonts=self.design.fonts, screenshot="jpeg" if screenshot else None, max_height=2400,
        )

    async def _save(self, html: str, note: str) -> dict[str, Any]:
        html = fragment_of(html)
        saved = await self.store.save_screen(
            self.session_id, self.screen.id,
            ScreenWrite(name=self.screen.name, platform=self.screen.platform, html=html, note=note[:400]),
            run_id=self.run_id, updated_by=self.user,
        )
        self.state.version = saved.version
        result = await self._render(html)
        self.state.checked_version = saved.version
        self.state.blocking = len(result.blocking)
        report = _report(result)
        await self.emit("screen.saved", {
            "screen_id": self.screen.id, "version": saved.version, "errors": report["errors"],
            "warnings": report["warnings"], "note": note[:200],
        })
        return {"ok": True, "version": saved.version, "chars": len(html), "lint": report}

    def functions(self) -> list[Callable[..., Awaitable[dict[str, Any]]]]:
        tools = self

        async def write_screen(html: str, note: str = "") -> dict[str, Any]:
            """Replace the whole screen with this HTML body fragment. Returns the lint report.

            Args:
                html: the complete body fragment of the screen.
                note: what this version does, in a few words.
            """
            tools.state.steps += 1
            return await tools._save(html, note or "write")

        async def edit_screen(old: str, new: str, replace_all: bool = False, note: str = "") -> dict[str, Any]:
            """Replace an exact snippet of the current HTML (must be unique unless replace_all). Returns lint.

            Args:
                old: exact text copied from the current HTML.
                new: replacement text.
                replace_all: replace every occurrence instead of requiring a unique one.
                note: what this edit fixes, in a few words.
            """
            tools.state.steps += 1
            current = await tools._current()
            count = current.count(old) if old else 0
            if count == 0:
                return {"ok": False, "error": "`old` was not found. Copy it exactly from read_screen (whitespace matters)."}
            if count > 1 and not replace_all:
                return {"ok": False, "error": f"`old` occurs {count} times; add surrounding text to make it unique."}
            updated = current.replace(old, new) if replace_all else current.replace(old, new, 1)
            return await tools._save(updated, note or "edit")

        async def read_screen() -> dict[str, Any]:
            """Return the current HTML of the screen (to copy exact snippets for edit_screen)."""
            html = await tools._current()
            return {"ok": True, "version": tools.state.version, "html": html or "(empty: call write_screen)"}

        async def check_screen(state: str = "") -> dict[str, Any]:
            """Render the screen and attach a screenshot to your next turn, with the lint report.

            Args:
                state: optional state id (data-state) to show, e.g. "error"; empty = default state.
            """
            tools.state.steps += 1
            html = await tools._current()
            if not html:
                return {"ok": False, "error": "The screen is empty; call write_screen first."}
            result = await tools._render(html, state=state or None, screenshot=True)
            if not state:
                tools.state.screenshot_version = tools.state.version
                tools.state.checked_version = tools.state.version
                tools.state.blocking = len(result.blocking)
            tools.state.pending_image = [
                types.Part.from_text(text=f"Screenshot of `{tools.screen.id}`" + (f" in state `{state}`" if state else "")
                                     + f" at {tools.width}px (version {tools.state.version})."),
                types.Part.from_bytes(data=result.image, mime_type="image/jpeg"),
            ]
            return {"ok": True, "version": tools.state.version, "screenshot": "attached to your next turn",
                    "lint": _report(result)}

        async def find_components(query: str) -> dict[str, Any]:
            """Search the design system components by name (e.g. "button", "input", "table").

            Args:
                query: words of the component name.
            """
            words = [w for w in query.lower().split() if w]
            hits = [c for c in tools.design.components if all(w in c["name"].lower() or w in c["id"] for w in words)]
            return {
                "ok": True,
                "components": [
                    {"name": c["name"], "props": c["props"], "variants": [v["id"] for v in c["variants"][:12]]}
                    for c in hits[:12]
                ],
                "note": "get_component(variant_id) returns the HTML." if hits else "No match: compose it with Tailwind.",
            }

        async def get_component(variant_id: str) -> dict[str, Any]:
            """Return the HTML of a design system component variant, to reuse in the screen.

            Args:
                variant_id: an id from find_components.
            """
            snippets = await tools.store.get_snippets(tools.design.id, [variant_id])
            html = snippets.get(variant_id)
            if html is None:
                return {"ok": False, "error": "Unknown variant id; use find_components."}
            return {"ok": True, "html": html[:SNIPPET_LIMIT], "truncated": len(html) > SNIPPET_LIMIT}

        async def find_images(query: str, orientation: str = "landscape") -> dict[str, Any]:
            """Search real photos for backgrounds, heroes, cards and thumbnails (CC / stock).

            Args:
                query: 2-4 English keywords describing the photo, e.g. "university library students".
                orientation: landscape, portrait or squarish.
            """
            tools.state.steps += 1
            images = await search_images(query, orientation, tools.unsplash_key)
            if not images:
                return {"ok": False, "error": "No photo found; try other keywords, or use a gradient/illustration."}
            return {"ok": True, "images": images[:6],
                    "use": "<img src=URL class='object-cover …'> or a background: bg-[url('URL')] bg-cover bg-center"}

        async def finish_screen(summary: str, tool_context: ToolContext) -> dict[str, Any]:
            """Declare the screen finished. Requires: no lint errors and a screenshot of the latest version.

            Args:
                summary: one or two sentences on what the screen contains, in the user's language.
            """
            s = tools.state
            if s.version == 0:
                return {"ok": False, "error": "Nothing written yet."}
            if s.checked_version != s.version or s.blocking:
                return {"ok": False, "error": f"Fix the {s.blocking} lint error(s) of the latest version first."}
            if s.screenshot_version != s.version:
                return {"ok": False, "error": "Call check_screen to look at the latest version before finishing."}
            s.finished, s.summary = True, summary
            tool_context.actions.skip_summarization = True  # end the turn: no further model call
            return {"ok": True, "finished": True}

        return [write_screen, edit_screen, read_screen, check_screen, find_components, get_component, find_images,
                finish_screen]

    async def attach_screenshot(self, callback_context: Any, llm_request: Any) -> None:
        """ADK before_model_callback: compact the history, then add the latest screenshot (this call only)."""
        llm_request.contents = compact_history(llm_request.contents)
        if self.state.pending_image:
            llm_request.contents.append(types.Content(role="user", parts=list(self.state.pending_image)))
            self.state.pending_image.clear()
