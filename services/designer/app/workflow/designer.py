"""The HTML designer: route a message, write the UI spec, build/edit screens with tools.

Stages (read by core/app/journey.py): requirement → specification → review_spec (human)
→ assembly → review_final (human) → finished. Chat-driven edits go requirement →
assembly → finished without reviews.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from google.genai import types

from ..core.errors import AppError
from ..designsystem.service import DesignContext, design_context
from ..models import DEFAULT_DESIGN_SYSTEM, RunStage, RunStatus, RunView, SessionView
from .schemas import DesignDecision, ScreenSpec, UiSpec
from .tools import ScreenTools

if TYPE_CHECKING:
    from .service import RunService

logger = logging.getLogger("designer_agent.designer")

INTENTS = {"chat": "chat", "clarify_design": "clarify_design", "propose_scope": "clarify_design",
           "start_design": "start_design", "edit_screens": "design"}
HISTORY_RUNS = 8
SOURCE_CHARS = 40_000
REFERENCE_CHARS = 5_000


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} more characters)"


class HtmlDesigner:
    def __init__(self, service: "RunService") -> None:
        self.service = service
        self.store = service.store
        self.events = service.events
        self.llm = service.llm
        self.prompts = service.prompts

    # ── helpers ──
    async def _emit(self, run: RunView, kind: str, payload: dict[str, Any]) -> None:
        await self.events.emit(run.id, run.revision, kind, payload)

    async def _stage(self, run: RunView, stage: RunStage, status: RunStatus = RunStatus.RUNNING, **fields: Any) -> RunView:
        run = await self.store.update_run(run.id, stage=stage, status=status, **fields)
        await self._emit(run, "stage.changed", {"stage": stage.value, "status": status.value})
        return run

    async def _usage(self, run: RunView, usage: dict[str, int], step: str) -> None:
        total = await self.store.get_artifact(run.id, run.revision, "token_usage") or {"steps": []}
        total["steps"].append({"step": step, **usage})
        for k in ("calls", "prompt_tokens", "output_tokens"):
            total[k] = total.get(k, 0) + usage.get(k, 0)
        await self.store.set_artifact(run.id, run.revision, "token_usage", total)
        await self._emit(run, "llm.usage", {"step": step, **usage, "run_total": {k: total[k] for k in ("calls", "prompt_tokens", "output_tokens")}})

    async def _session_runs(self, session: SessionView, current: RunView) -> list[RunView]:
        runs = [r for r in await self.store.list_runs(session.id) if r.id != current.id]
        return list(reversed(runs))

    def _history(self, runs: list[RunView], *, first_limit: int, limit: int = 1500) -> str:
        lines = []
        for i, r in enumerate(runs[-HISTORY_RUNS:] if len(runs) > HISTORY_RUNS else runs):
            lines.append(f"User: {_clip(r.prompt, first_limit if i == 0 else limit)}")
            if r.assistant_message:
                lines.append(f"Designer: {_clip(r.assistant_message, 800)}")
        return "\n".join(lines) or "(none)"

    def _design_text(self, design: DesignContext) -> str:
        if design.id == DEFAULT_DESIGN_SYSTEM or not design.components:
            return f"{design.name}. No component library: compose with Tailwind utilities and the theme tokens."
        tokens = [line.strip().split(":")[0][2:] for line in design.theme_css.splitlines()
                  if line.strip().startswith("--") and "Imported" not in line]
        colors = [t.removeprefix("color-") for t in tokens if t.startswith("color-")][-40:]
        texts = sorted({t.removeprefix("text-").split("--")[0] for t in tokens if t.startswith("text-")})[:24]
        shadows = [t.removeprefix("shadow-") for t in tokens if t.startswith("shadow-")][:12]
        components = ", ".join(f"{c['name']}" + (f" ({'/'.join(c['props'])})" if c["props"] else "")
                               for c in design.components[:80])
        return (
            f"{design.name} (imported from Figma). Color utilities: {', '.join(colors)}. "
            f"Text styles: {', '.join('text-' + t for t in texts)}. Shadows: {', '.join('shadow-' + s for s in shadows)}. "
            f"{len(design.components)} components, e.g.: {components}."
        )

    # ── stage 1: route ──
    async def analyze(self, run_id: UUID, feedback: str = "None") -> None:
        run = await self.store.get_run(run_id)
        session = await self.store.get_session(run.session_id)
        run = await self._stage(run, RunStage.REQUIREMENT)
        runs = await self._session_runs(session, run)
        screens = await self.store.list_screens(session.id)
        brief = await self.store.get_design_brief(session.id)
        usage: dict[str, int] = {}
        decision = await self.llm.structured(
            prompt=self.prompts.render(
                "router",
                brief=brief.model_dump_json(exclude_defaults=True) or "{}",
                screens=json.dumps([{"id": s.id, "name": s.name, "platform": s.platform} for s in screens], ensure_ascii=False) or "[]",
                history=self._history(runs, first_limit=6000),
                message=_clip(run.prompt, 20_000),
            ),
            schema=DesignDecision,
            usage=usage,
        )
        await self._usage(run, usage, "router")
        if decision.brief.screens:
            await self.store.save_design_brief(session.id, decision.brief)
            brief = decision.brief
        intent = INTENTS[decision.intent]
        await self._emit(run, "assistant.message", {"intent": decision.intent, "message": decision.reply})
        if decision.intent in {"chat", "clarify_design", "propose_scope"}:
            await self._stage(run, RunStage.FINISHED, RunStatus.COMPLETED, intent=intent, assistant_message=decision.reply)
            return
        if decision.intent == "start_design":
            run = await self.store.update_run(run.id, intent=intent, assistant_message=decision.reply)
            await self.write_spec(run.id, feedback="None")
            return
        # edit_screens: change existing screens (or add new ones) directly, no review gates.
        spec = await self._current_spec(session, runs, screens)
        for screen_id in decision.target_screen_ids:
            if spec.screen(screen_id) is None:
                named = next((s for s in brief.screens if s.id == screen_id), None)
                spec.screens.append(ScreenSpec(
                    id=screen_id, name=named.name if named else screen_id.replace("-", " ").title(),
                    platform=(named.platforms[0] if named and named.platforms else spec.screens[0].platform if spec.screens else "desktop"),
                    purpose=(named.purpose if named else decision.instruction),
                ))
        targets = [s for s in decision.target_screen_ids if spec.screen(s)] or [s.id for s in spec.screens]
        run = await self.store.update_run(run.id, intent=intent, assistant_message=decision.reply, specification=spec)
        await self.build(run.id, targets, instruction=decision.instruction or run.prompt, review=False)

    async def _current_spec(self, session: SessionView, runs: list[RunView], screens) -> UiSpec:
        for r in reversed(runs):
            if r.specification and r.specification.get("schema_version") == "html-1":
                return UiSpec.model_validate(r.specification)
        if screens:
            return UiSpec(screens=[ScreenSpec(id=s.id, name=s.name, platform=s.platform) for s in screens])
        return UiSpec.model_construct(schema_version="html-1", style_direction="", screens=[])

    # ── stage 2: specification ──
    async def write_spec(self, run_id: UUID, feedback: str = "None") -> None:
        run = await self.store.get_run(run_id)
        session = await self.store.get_session(run.session_id)
        run = await self._stage(run, RunStage.SPECIFICATION)
        runs = await self._session_runs(session, run)
        brief = await self.store.get_design_brief(session.id)
        design = await design_context(self.store, session)
        source = self._history(runs + [run], first_limit=SOURCE_CHARS, limit=4000)
        usage: dict[str, int] = {}
        spec = await self.llm.structured(
            prompt=self.prompts.render(
                "spec", design_system=self._design_text(design), brief=brief.model_dump_json(exclude_defaults=True),
                feedback=feedback or "None", context=source,
            ),
            schema=UiSpec,
            usage=usage,
        )
        await self._usage(run, usage, "spec")
        run = await self._stage(run, RunStage.REVIEW_SPEC, RunStatus.WAITING_REVIEW, specification=spec)
        await self._emit(run, "review.required", {"checkpoint": "specification", "screens": [s.id for s in spec.screens]})

    # ── stage 3: build ──
    async def build(self, run_id: UUID, screen_ids: list[str] | None = None, *, instruction: str = "", review: bool = True) -> None:
        run = await self.store.get_run(run_id)
        session = await self.store.get_session(run.session_id)
        if not run.specification:
            raise AppError("SPEC_MISSING", "No specification", "Approve a specification before building.", 409)
        spec = UiSpec.model_validate(run.specification)
        run = await self._stage(run, RunStage.ASSEMBLY)
        design = await design_context(self.store, session)
        targets = [s for s in (screen_ids or [s.id for s in spec.screens]) if spec.screen(s)]
        existing = {s.id: s for s in await self.store.list_screens(session.id, with_html=True)}
        summaries = []
        reference = next((s for sid, s in existing.items() if sid not in targets and s.html), None)
        for index, screen_id in enumerate(targets):
            screen = spec.screen(screen_id)
            await self._emit(run, "screen.started", {"screen_id": screen_id, "name": screen.name, "index": index, "total": len(targets)})
            current = existing.get(screen_id)
            summary = await self._build_screen(run, session, spec, screen, design, reference,
                                               current.html if current and instruction else "", instruction)
            summaries.append(f"**{screen.name}**: {summary}")
            if reference is None:
                reference = await self.store.get_screen(session.id, screen_id)
        message = "\n".join(summaries)
        if review:
            run = await self._stage(run, RunStage.REVIEW_FINAL, RunStatus.WAITING_REVIEW, assistant_message=message)
            await self._emit(run, "review.required", {"checkpoint": "final", "screens": targets})
        else:
            await self._stage(run, RunStage.FINISHED, RunStatus.COMPLETED, assistant_message=message)

    async def _build_screen(self, run, session, spec: UiSpec, screen: ScreenSpec, design: DesignContext,
                            reference, current_html: str, instruction: str) -> str:
        settings = self.service.settings
        tools = ScreenTools(
            store=self.store, renderer=self.service.renderer, session_id=session.id, run_id=run.id, screen=screen,
            design=design, emit=lambda kind, payload: self._emit(run, kind, payload), user="designer-agent",
            unsplash_key=settings.unsplash_access_key,
        )
        others = [f"{s.id} ({s.name})" for s in spec.screens if s.id != screen.id]
        reference_text = ""
        if reference is not None and reference.html:
            reference_text = (
                f"Reference — screen `{reference.id}` of the same product. Keep its navigation, header and visual "
                f"language consistent:\n```html\n{_clip(reference.html, REFERENCE_CHARS)}\n```"
            )
        prompt = self.prompts.render(
            "builder", width=tools.width, screen=screen.model_dump_json(exclude_defaults=True),
            style=spec.style_direction or "Clean, modern product UI.", design_system=self._design_text(design),
            others=", ".join(others) or "(none)", reference=reference_text,
            instruction=f"Change requested by the user: {instruction}" if current_html else "",
        )
        if current_html:
            # Edits start from the saved version (kept in history); finish needs a check of the new one.
            tools.state.version = (await self.store.get_screen(session.id, screen.id)).version
            # The HTML is fetched with read_screen (compacted out of later turns), not inlined here.
            text = (f"`{screen.id}` exists (version {tools.state.version}). Call read_screen, apply the requested change "
                    f"with edit_screen (write_screen only for a large rework), check_screen, then finish_screen.")
        else:
            text = f"Design the screen `{screen.id}` now: write_screen, review lint and screenshot, refine, finish_screen."
        usage: dict[str, int] = {}
        try:
            await self.llm.run_tools(
                prompt=prompt,
                tools=tools.functions(),
                before_model_callback=tools.attach_screenshot,
                max_turns=settings.designer_page_max_steps,
                message=types.Content(role="user", parts=[types.Part.from_text(text=text)]),
                timeout_seconds=settings.designer_page_timeout_seconds,
                model=settings.effective_designer_model,
                stop_when=lambda: tools.state.finished,
                progress_token=lambda: f"{tools.state.version}:{tools.state.steps}",
                continuation_message="Continue with the tools: fix lint errors, check_screen, then finish_screen.",
                usage=usage,
                force_tools=True,
            )
        except Exception as error:  # noqa: BLE001 — a usable saved screen is kept; otherwise the run fails
            if tools.state.version and not tools.state.blocking and tools.state.checked_version == tools.state.version:
                logger.warning("Screen %s accepted without finish_screen: %s", screen.id, error)
                await self._emit(run, "screen.warning", {"screen_id": screen.id, "message": f"Dừng sớm: {error}"})
            else:
                await self._usage(run, usage, f"build:{screen.id}")
                raise
        await self._usage(run, usage, f"build:{screen.id}")
        await self._emit(run, "screen.finished", {"screen_id": screen.id, "version": tools.state.version,
                                                  "summary": tools.state.summary})
        return tools.state.summary or "Đã dựng xong."

    # ── review feedback on the final design ──
    async def targets_for(self, run: RunView, feedback: str) -> list[str]:
        spec = UiSpec.model_validate(run.specification)
        named = [s.id for s in spec.screens if s.id in feedback or s.name.lower() in feedback.lower()]
        return named or [s.id for s in spec.screens]
