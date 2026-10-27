"""The HTML designer: route a message, write the UI spec + art direction, build/edit screens.

Stages (read by core/app/journey.py): requirement → specification → review_spec (human)
→ assembly → review_final (human) → finished. Chat-driven edits go requirement →
assembly → finished without reviews.

A screen is one draft call plus at most ``designer_review_rounds`` review calls (screenshot +
DOM lint + required texts → OK / edit blocks). Screens after the first are built in parallel.
Design knowledge comes from the vendored skills (``app.knowledge``), retrieved per product
and per screen, so no domain or platform is hard-coded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any
from uuid import UUID

from .. import knowledge
from ..core.errors import AppError
from ..designsystem.direction import direction_theme
from ..designsystem.service import DesignContext, design_context
from ..models import DEFAULT_DESIGN_SYSTEM, SCREEN_WIDTHS, RunStage, RunStatus, RunView, ScreenWrite, SessionView
from ..render import fragment_of
from ..render.assets import inline_assets
from ..render.images import find_images
from .patches import apply_reply, extract_html
from .schemas import DesignDecision, ScreenSpec, UiSpec

if TYPE_CHECKING:
    from .service import RunService

logger = logging.getLogger("designer_agent.designer")

INTENTS = {"chat": "chat", "clarify_design": "clarify_design", "propose_scope": "clarify_design",
           "start_design": "start_design", "edit_screens": "design"}
HISTORY_RUNS = 8
SOURCE_CHARS = 40_000
REFERENCE_CHARS = 3_500
MAX_FINDINGS = 8


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} more characters)"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


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
        total = await self.store.get_run_data(run.id, run.revision, "token_usage") or {"steps": []}
        total["steps"].append({"step": step, **usage})
        for k in ("calls", "prompt_tokens", "output_tokens"):
            total[k] = total.get(k, 0) + usage.get(k, 0)
        await self.store.set_run_data(run.id, run.revision, "token_usage", total)
        await self._emit(run, "llm.usage", {"step": step, **usage,
                                            "run_total": {k: total[k] for k in ("calls", "prompt_tokens", "output_tokens")}})

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

    def _design_text(self, design: DesignContext, query: str = "") -> str:
        """Imported design system: its token names and the components relevant to ``query``."""
        if design.id == DEFAULT_DESIGN_SYSTEM or not design.components:
            return "None imported: use the art direction and the theme tokens."
        tokens = [line.strip().split(":")[0][2:] for line in design.theme_css.splitlines()
                  if line.strip().startswith("--") and "Imported" not in line]
        colors = [t.removeprefix("color-") for t in tokens if t.startswith("color-")][-40:]
        texts = sorted({t.removeprefix("text-").split("--")[0] for t in tokens if t.startswith("text-")})[:24]
        words = set(re.findall(r"[a-z]+", query.lower()))
        relevant = [c for c in design.components if words & set(re.findall(r"[a-z]+", c["name"].lower()))][:20]
        names = ", ".join(c["name"] + (f" ({'/'.join(c['props'])})" if c["props"] else "") for c in relevant or design.components[:20])
        return (f"{design.name} (imported from Figma) — match its look. Color utilities: {', '.join(colors)}. "
                f"Text styles: {', '.join('text-' + t for t in texts)}. Components: {names}.")

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

    # ── stage 2: specification + art direction ──
    async def write_spec(self, run_id: UUID, feedback: str = "None") -> None:
        run = await self.store.get_run(run_id)
        session = await self.store.get_session(run.session_id)
        run = await self._stage(run, RunStage.SPECIFICATION)
        runs = await self._session_runs(session, run)
        brief = await self.store.get_design_brief(session.id)
        design = await design_context(self.store, session)
        imported = design.id != DEFAULT_DESIGN_SYSTEM and bool(design.components)
        query = brief.design_query or f"{brief.product_name} {brief.product_description}"
        usage: dict[str, int] = {}
        spec = await self.llm.structured(
            prompt=self.prompts.render(
                "spec",
                profile=knowledge.profile_text(knowledge.product_profile(query)),
                skill=knowledge.frontend_design_skill(),
                palette_rule=("A design system is imported: set `palette` to null and keep its colors."
                              if imported else "Choose them for this product; the reference palette is a starting point."),
                design_system=self._design_text(design, query),
                brief=brief.model_dump_json(exclude_defaults=True),
                feedback=feedback or "None",
                context=self._history(runs + [run], first_limit=SOURCE_CHARS, limit=4000),
            ),
            schema=UiSpec,
            usage=usage,
        )
        await self._usage(run, usage, "spec")
        theme = None if imported else direction_theme(spec.design.model_dump())
        await self.store.set_session_visual_theme(session.id, theme)
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
        reference = next((s.html for sid, s in existing.items() if sid not in targets and s.html), None)
        summaries: dict[str, str] = {}

        async def one(index: int, screen_id: str, ref: str | None) -> None:
            screen = spec.screen(screen_id)
            await self._emit(run, "screen.started", {"screen_id": screen_id, "name": screen.name,
                                                     "index": index, "total": len(targets)})
            current = existing.get(screen_id)
            summaries[screen_id] = await self._build_screen(
                run, session, spec, screen, design, ref, current.html if current and instruction else "", instruction)

        # The first screen sets the shell (navigation, header, rhythm); the others follow it in parallel.
        if targets and reference is None:
            await one(0, targets[0], None)
            first = await self.store.get_screen(session.id, targets[0])
            reference, rest = (first.html if first else None), list(enumerate(targets))[1:]
        else:
            rest = list(enumerate(targets))
        limit = asyncio.Semaphore(max(1, self.service.settings.designer_parallel_screens))

        async def limited(index: int, screen_id: str) -> None:
            async with limit:
                await one(index, screen_id, reference)

        await asyncio.gather(*(limited(i, sid) for i, sid in rest))
        message = "\n".join(f"**{spec.screen(sid).name}**: {summaries.get(sid, '')}" for sid in targets)
        if review:
            run = await self._stage(run, RunStage.REVIEW_FINAL, RunStatus.WAITING_REVIEW, assistant_message=message)
            await self._emit(run, "review.required", {"checkpoint": "final", "screens": targets})
        else:
            await self._stage(run, RunStage.FINISHED, RunStatus.COMPLETED, assistant_message=message)

    def _direction_text(self, spec: UiSpec) -> str:
        d = spec.design
        lines = [d.mood or spec.style_direction or "Derive it from the product."]
        if d.palette:
            lines.append("Palette: " + ", ".join(f"{k}={v}" for k, v in d.palette.model_dump().items()))
        lines.append(f"Fonts: headings {d.heading_font}, body {d.body_font}; radius {d.radius}; density {d.density}.")
        if d.do:
            lines.append("Do: " + "; ".join(d.do))
        if d.dont:
            lines.append("Don't: " + "; ".join(d.dont))
        return "\n".join(lines)

    async def _images(self, screen: ScreenSpec) -> str:
        key = self.service.settings.unsplash_access_key
        found = await asyncio.gather(*(find_images(n.query, n.orientation, key) for n in screen.imagery))
        lines = [f"- {need.slot}: {imgs[0]['url']}" + (f" (alternative: {imgs[1]['url']})" if len(imgs) > 1 else "")
                 for need, imgs in zip(screen.imagery, found) if imgs]
        return "\n".join(lines) or "(none — use no photography)"

    async def _check(self, html: str, screen: ScreenSpec, width: int, design: DesignContext,
                     project_id: str | None):
        result = await self.service.renderer.render(
            await inline_assets(html, project_id), width=width, theme_css=design.theme_css, fonts=design.fonts,
            screenshot="jpeg", max_height=2400)
        text = _norm(result.text)
        missing = [m for m in screen.must_show if _norm(m) not in text]
        lines = [f"- {f['severity'].upper()} {f['rule']}: {f['message']}"
                 + (f" e.g. {f['elements'][0]['html'][:140]}" if f.get("elements") else "")
                 for f in sorted(result.findings, key=lambda f: {"error": 0, "warning": 1, "info": 2}[f["severity"]])[:MAX_FINDINGS]]
        if missing:
            lines.insert(0, "- ERROR missing-text: required texts not on the screen: " + "; ".join(missing))
        blocking = bool(missing) or bool(result.blocking)
        score = (len(missing), len(result.blocking))  # lower is better; an edit must not raise it
        return result, "\n".join(lines) or "- none", blocking, score

    async def _build_screen(self, run, session, spec: UiSpec, screen: ScreenSpec, design: DesignContext,
                            reference: str | None, current_html: str, instruction: str) -> str:
        settings = self.service.settings
        width = SCREEN_WIDTHS.get(screen.platform, 1440)
        query = screen.ux_query or f"{screen.name} {screen.purpose}"
        system = self.prompts.render(
            "builder", width=width, direction=self._direction_text(spec),
            design_system=self._design_text(design, query), skill=knowledge.frontend_design_skill(),
        )
        usage: dict[str, int] = {}
        model = settings.effective_designer_model
        timeout = settings.designer_page_timeout_seconds

        async def save(html: str, note: str) -> str:
            html = fragment_of(html)
            saved = await self.store.save_screen(
                session.id, screen.id, ScreenWrite(name=screen.name, platform=screen.platform, html=html, note=note[:400]),
                run_id=run.id, updated_by="designer-agent")
            await self._emit(run, "screen.saved", {"screen_id": screen.id, "version": saved.version, "note": note[:200]})
            return html

        if current_html:
            html, task = current_html, f"Apply this change requested by the user to the screen: {instruction}"
        else:
            ux = knowledge.ux_rules(query, screen.platform)
            ux += knowledge.tailwind_rules(query, 3)
            if re.search(r"chart|graph|trend|biểu đồ|thống kê|report", f"{query} {' '.join(screen.sections)}", re.I):
                ux += knowledge.chart_rules(query)
            others = ", ".join(f"{s.id} ({s.name})" for s in spec.screens if s.id != screen.id) or "(none)"
            ref = (f"Reference — the shell of another screen of this product. Reuse its navigation/header structure "
                   f"and visual language:\n{_clip(reference, REFERENCE_CHARS)}") if reference else ""
            draft = await self.llm.generate(
                system=system,
                text=self.prompts.render(
                    "draft", screen_id=screen.id,
                    screen=screen.model_dump_json(exclude_defaults=True, exclude={"must_show", "rules", "imagery", "ux_query"}),
                    must_show="; ".join(screen.must_show) or "(none)", rules="; ".join(screen.rules) or "(none)",
                    images=await self._images(screen), others=others, ux="\n".join(f"- {u}" for u in ux), reference=ref,
                ),
                usage=usage, model=model, timeout_seconds=timeout,
            )
            html = await save(extract_html(draft), "draft")
            task = "Review this screen you built and finish it."
        result, checks, blocking, score = await self._check(html, screen, width, design, session.project_id)
        for round_no in range(max(1, settings.designer_review_rounds)):
            if round_no and not blocking:
                break  # one visual review always happens; later rounds only to clear errors
            reply = await self.llm.generate(
                system=system,
                text=self.prompts.render("review", task=task, width=width, checks=checks,
                                         checklist=knowledge.review_checklist(), html=html),
                images=[result.image] if result.image else None, usage=usage, model=model, timeout_seconds=timeout,
            )
            edit = apply_reply(html, reply)
            notes = [f"These edit blocks did not apply: {'; '.join(edit.failed)}."] if edit.failed else []
            if edit.applied:
                # Keep an edit only if it does not make the screen worse (lost texts, new blocking errors).
                candidate = await self._check(edit.html, screen, width, design, session.project_id)
                if candidate[3] <= score:
                    html = await save(edit.html, "rework" if edit.rewrite else f"review {round_no + 1}")
                    result, checks, blocking, score = candidate
                else:
                    logger.info("Screen %s: rejected an edit that worsened the checks %s -> %s",
                                screen.id, score, candidate[3])
                    notes.append("Your last change was rejected because it made the checks worse:\n" + candidate[1])
            elif edit.ok and not blocking:
                break
            task = " ".join(notes + ["Continue: fix what the checks report."])
        await self._usage(run, usage, f"build:{screen.id}")
        await self._emit(run, "screen.finished", {"screen_id": screen.id})
        return screen.purpose or "Đã dựng xong."

    # ── review feedback on the final design ──
    async def targets_for(self, run: RunView, feedback: str) -> list[str]:
        spec = UiSpec.model_validate(run.specification)
        named = [s.id for s in spec.screens if s.id in feedback or s.name.lower() in feedback.lower()]
        return named or [s.id for s in spec.screens]
