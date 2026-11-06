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
import base64
import json
import logging
import re
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, Field

from .. import knowledge
from ..core.errors import AppError
from ..designsystem.direction import direction_theme
from ..designsystem.service import DesignContext, design_context
from ..models import DEFAULT_DESIGN_SYSTEM, SCREEN_WIDTHS, RunStage, RunStatus, RunView, ScreenWrite, SessionView, StyleCandidate
from ..render import fragment_of
from ..render.assets import inline_assets
from ..render.images import find_images
from .preview_assets import asset_by_id, inline_svg, relevant_assets
from .patches import apply_reply, extract_html
from .schemas import DesignDecision, Palette, ScreenSpec, StylePreviewPlan, UiSpec

if TYPE_CHECKING:
    from .service import RunService

logger = logging.getLogger("designer_agent.designer")

INTENTS = {"chat": "chat", "clarify_design": "clarify_design", "propose_scope": "gather", "gather": "gather",
           "start_design": "start_design", "edit_screens": "design"}
HISTORY_RUNS = 8
SOURCE_CHARS = 40_000
REFERENCE_CHARS = 3_500
MAX_FINDINGS = 8


class _StylePreviewReviewItem(BaseModel):
    key: str
    ready: bool
    issues: list[str] = Field(default_factory=list, max_length=3)


class _StylePreviewReviewBatch(BaseModel):
    reviews: list[_StylePreviewReviewItem] = Field(min_length=1, max_length=3)


class _ScreenAudit(BaseModel):
    ready: bool
    issues: list[str] = Field(default_factory=list, max_length=5)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} more characters)"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _representative_preview_screen(screens):
    """Pick the most informative confirmed screen without relying on domain keywords."""
    if not screens:
        return None

    def information_score(screen):
        content = screen.content_outline or []
        actions = screen.actions or []
        states = screen.states or []
        return (
            len(content) + len(actions),
            len(content),
            len(actions),
            len(states),
            sum(len(str(item)) for item in content + actions + states),
            len((screen.purpose or "").strip()),
            "mobile" in (screen.platforms or []),
        )

    return max(enumerate(screens), key=lambda pair: (information_score(pair[1]), -pair[0]))[1]


def _style_preview_reviews(response: str, candidates: list[StyleCandidate]) -> dict[str, list[str]] | None:
    """Parse critic JSON; return None when the reviewer response cannot be trusted."""
    start, end = response.find("{"), response.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(response[start:end + 1])
    except json.JSONDecodeError:
        return None
    rows = payload.get("reviews") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    by_key = {row.get("key"): row for row in rows if isinstance(row, dict)}
    issues: dict[str, list[str]] = {}
    for candidate in candidates:
        row = by_key.get(candidate.key)
        if not row or row.get("ready") is not True:
            notes = row.get("issues", []) if row else []
            issues[candidate.key] = [str(note) for note in notes if str(note).strip()][:3]
            if not issues[candidate.key]:
                issues[candidate.key] = [
                    "Inspect the screenshot and improve its product fit, legibility, source fidelity, and visual distinction."
                ]
    return issues


def _candidate_theme(candidate: StyleCandidate) -> dict[str, Any] | None:
    """Build renderer tokens from the exact palette/font contract shown in this option."""
    if not candidate.palette:
        return None
    palette = Palette.model_validate(candidate.palette)
    return direction_theme({
        "palette": palette.model_dump(),
        "heading_font": candidate.heading_font,
        "body_font": candidate.body_font,
        "radius": candidate.radius,
    })


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
                design_rules=knowledge.ui_ux_design_rules(),
                history=self._history(runs, first_limit=6000),
                message=_clip(run.prompt, 20_000),
            ),
            schema=DesignDecision,
            usage=usage,
        )
        await self._usage(run, usage, "router")
        normalized_prompt = _norm(run.prompt)
        if re.search(r"\b(chọn|choose|select)\b", normalized_prompt):
            selected = next((item for item in brief.style_candidates
                             if item.key.casefold() in normalized_prompt or item.name.casefold() in normalized_prompt), None)
            if selected:
                brief.selected_style_key = selected.key
                brief.style_name = selected.name
                brief.style_direction = selected.direction or selected.tagline
                brief.selected_style_contract = selected.model_dump(mode="json")
                decision.brief = brief
                decision.intent = "start_design"
                decision.reply = f"Đã chọn phong cách {selected.name}. Mình sẽ dùng hướng này để lập UI spec cho các screen đã chốt."
        # Style candidates are generated and stored by the backend; do not let a
        # later router turn accidentally replace or hallucinate the gallery.
        decision.brief.style_candidates = brief.style_candidates
        decision.brief.style_preview_shown = brief.style_preview_shown
        decision.brief.selected_style_key = brief.selected_style_key
        decision.brief.style_name = brief.style_name
        decision.brief.style_direction = brief.style_direction
        decision.brief.selected_style_contract = brief.selected_style_contract
        if decision.brief.screens or decision.brief.product_description:
            await self.store.save_design_brief(session.id, decision.brief)
            brief = decision.brief
        intent = INTENTS[decision.intent]
        if decision.intent == "start_design" and brief.missing_fields():
            # Keep the user's partial decisions and continue gathering instead of
            # entering spec generation with unresolved screen content.
            intent = "gather"
            decision.intent = "gather"
            unresolved = [screen.name for screen in brief.screens if not screen.confirmed or screen.open_questions]
            detail = ", ".join(unresolved) or "phạm vi hoặc nền tảng"
            decision.reply = (
                f"Mình đã lưu các lựa chọn của bạn. Trước khi lập UI spec, mình cần chốt thêm "
                f"nội dung/chức năng cho: {detail}. Bạn có thể trả lời các mục còn mở ở trên."
            )
        valid_style_choice = (
            brief.style_preview_shown
            and bool(brief.style_direction)
            and any(candidate.key == brief.selected_style_key for candidate in brief.style_candidates)
        )
        if decision.intent == "start_design" and not valid_style_choice:
            brief.selected_style_key = ""
            brief.style_name = None
            brief.style_direction = ""
            brief.selected_style_contract = {}
            await self.store.save_design_brief(session.id, brief)
            await self._offer_style_previews(run, session, brief)
            return
        await self._emit(run, "assistant.message", {"intent": decision.intent, "message": decision.reply})
        if decision.intent in {"chat", "clarify_design", "propose_scope", "gather"}:
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

    async def _offer_style_previews(self, run: RunView, session: SessionView, brief) -> None:
        """Render three visual treatments of one confirmed screen and offer them in chat."""
        screen = _representative_preview_screen(brief.screens)
        if screen is None:
            raise AppError("STYLE_PREVIEW_UNAVAILABLE", "No confirmed screen is available for a style preview",
                           "Confirm at least one screen before choosing a visual style.", 409, True,
                           action="Confirm the screen scope.")
        platforms = screen.platforms or brief.platforms or ["mobile"]
        platform = "mobile" if "mobile" in platforms else platforms[0]
        width = SCREEN_WIDTHS.get(platform, 390)
        height = 900 if platform == "mobile" else 920
        design = await design_context(self.store, session)
        query = screen.name + " " + screen.purpose
        screen_context = json.dumps({
            "screen_name": screen.name,
            "purpose": screen.purpose,
            "platform": platform,
            "confirmed_visible_regions": screen.content_outline,
            "confirmed_actions": screen.actions,
            "behavioral_states_reference_only": screen.states,
        }, ensure_ascii=False)
        settings = self.service.settings
        preview_theme = design.theme_css if design.id != DEFAULT_DESIGN_SYSTEM else None
        preview_fonts = design.fonts if design.id != DEFAULT_DESIGN_SYSTEM else None
        product_query = brief.design_query or f"{brief.product_name} {brief.product_description} {platform}"
        preview_assets = relevant_assets(f"{product_query} {screen.name} {screen.purpose}")
        asset_catalog = [{key: value for key, value in asset.items() if key != "path"}
                         for asset in preview_assets]

        total_usage: dict[str, int] = {}

        def add_usage(usage: dict[str, int]) -> None:
            for key, value in usage.items():
                total_usage[key] = total_usage.get(key, 0) + value

        # Plan the visual directions from the live product/screen brief on every
        # gallery run. The knowledge catalogue informs the product context, while
        # the art directions themselves stay specific to this project.
        plan_usage: dict[str, int] = {}
        design_knowledge = knowledge.profile_text(knowledge.product_profile(product_query))
        try:
            plan = await self.llm.structured(
                prompt=self.prompts.render(
                    "style-preview-plan",
                    product=brief.product_name or "Product",
                    product_context=brief.product_description or "",
                    design_query=product_query,
                    design_system=(design.name + "\n" + design.theme_css[:5000]
                                   if design.id != DEFAULT_DESIGN_SYSTEM else design_knowledge),
                    screen=screen_context,
                    available_assets=json.dumps(asset_catalog, ensure_ascii=False),
                ),
                schema=StylePreviewPlan,
                model=settings.effective_designer_model,
                usage=plan_usage,
            )
            candidates = plan.options
        except Exception as error:
            logger.warning("Project-aware style planning failed; using retrieved style directions: %s", error)
            found = knowledge.style_preview_candidates(product_query)
            candidates = [StyleCandidate(**item, recommended=index == 0) for index, item in enumerate(found[:3])]
            if len(candidates) < 3:
                raise AppError("STYLE_PREVIEW_UNAVAILABLE", "Could not create three style directions",
                               "Retry the run to plan style previews.", 502, True,
                               action="Retry the run.") from error
        add_usage(plan_usage)
        brief.style_candidates = list(candidates)
        await self.store.save_design_brief(session.id, brief)

        async def render_candidate(
            candidate: StyleCandidate,
            *,
            review_feedback: str = "",
            previous_html: str = "",
        ) -> dict[str, Any]:
            usage: dict[str, int] = {}
            assigned_asset = asset_by_id(candidate.preview_asset_id, preview_assets) if candidate.preview_asset_id else None
            option_theme = _candidate_theme(candidate) if design.id == DEFAULT_DESIGN_SYSTEM else None
            option_theme_css = "\n".join(part for part in (
                design.theme_css if design.id != DEFAULT_DESIGN_SYSTEM else "",
                option_theme.get("css") if option_theme else "",
            ) if part) or None
            option_fonts = (option_theme.get("fonts") if option_theme else None) or (
                design.fonts if design.id != DEFAULT_DESIGN_SYSTEM else None
            )
            asset_description = "(none — use an original motif only if appropriate)"
            asset_data = ""
            if assigned_asset:
                asset_description = (
                    f"{assigned_asset['title']} illustration, Storyset {assigned_asset['style']} style. "
                    f"{assigned_asset['description']} Use the complete illustration as a large decorative background/scene layer "
                    "in a dedicated hero or screen-background region; it is not a logo, app icon, badge, or header ornament. "
                    "Keep the actual wordmark separate and keep text/controls readable above the image."
                )
                asset_data = inline_svg(assigned_asset)
            system = self.prompts.render(
                "builder", width=width,
                direction=(f"Style option '{candidate.name}' is the visual authority for this preview. "
                           f"Direction: {candidate.direction or candidate.tagline}. "
                           f"Visual contract: {candidate.model_dump_json(exclude={'key', 'name', 'tagline', 'direction', 'recommended'})}. "
                           "Make its composition, typography, surfaces, color balance and product-specific visual motif unmistakable; "
                           "do not fall back to a generic form or default style."),
                design_system=self._design_text(design, query),
                skill=knowledge.frontend_design_skill() + "\n\n" + knowledge.style_preview_skill(),
                design_rules=knowledge.ui_ux_design_rules(),
            )
            fragment = await self.llm.generate(
                system=system,
                text=self.prompts.render(
                    "style-preview", width=width, product=brief.product_name or "Product",
                    product_context=brief.product_description or "",
                    platform=platform,
                    screen=screen_context, style_name=candidate.name,
                    style_direction=candidate.direction or candidate.tagline,
                    assigned_visual_asset=asset_description,
                    visual_contract=candidate.model_dump_json(exclude={"key", "name", "tagline", "direction", "recommended"}),
                    review_feedback=review_feedback or "(none)",
                    previous_html=previous_html or "(none)",
                ),
                usage=usage, model=settings.effective_designer_model,
                timeout_seconds=settings.designer_page_timeout_seconds,
            )
            html = fragment_of(extract_html(fragment))
            render_html = html
            asset_included = False
            if assigned_asset and asset_data:
                if "__DESIGNER_PREVIEW_ASSET__" in render_html:
                    render_html = render_html.replace("__DESIGNER_PREVIEW_ASSET__", asset_data)
                    asset_included = True
                else:
                    logger.warning("Style preview %s did not include its assigned illustration token", candidate.key)
            result = await self.service.renderer.render(
                render_html, width=width, height=height,
                theme_css=option_theme_css or preview_theme, fonts=option_fonts or preview_fonts, screenshot="jpeg",
                scale=0.7, lint=True, axe=True, strict_touch_targets=(platform == "mobile"), max_height=1200,
            )
            add_usage(usage)
            return {
                "key": candidate.key, "name": candidate.name, "tagline": candidate.tagline,
                "recommended": candidate.recommended,
                "asset_credit": assigned_asset.get("credit", "") if asset_included and assigned_asset else "",
                "asset_source_url": assigned_asset.get("source_url", "") if asset_included and assigned_asset else "",
                "image": f"data:{result.mime or 'image/jpeg'};base64,{base64.b64encode(result.image or b'').decode('ascii')}",
                "html": html,
                "rendered_image": result.image,
                "qa_errors": [finding for finding in result.blocking],
            }

        previews = await asyncio.gather(*(render_candidate(candidate) for candidate in candidates))

        def static_issues(items: list[dict[str, Any]]) -> dict[str, list[str]]:
            failed: dict[str, list[str]] = {}
            for item in items:
                if item.get("qa_errors"):
                    failed[item["key"]] = [
                        (
                            f"{finding.get('rule')}: {finding.get('message')} "
                            "Affected visible nodes: " + "; ".join(
                                " / ".join(part for part in (
                                    str(node.get("text") or "").strip(),
                                    str(node.get("html") or "").strip(),
                                ) if part)
                                for node in finding.get("elements", [])[:3]
                            ) + ". Keep all text and interactive controls inside their visible content container; "
                            "only decorative imagery may intentionally crop inside a dedicated background region. Rerender."
                        )
                        for finding in item["qa_errors"]
                    ]
            return failed

        async def critique_previews() -> dict[str, list[str]] | None:
            usage: dict[str, int] = {}
            try:
                response = await self.llm.generate(
                    system=self.prompts.render("style-preview-review"),
                    text=("Approved screen data:\n" + screen_context + "\n\nStyle options in screenshot order:\n" +
                          json.dumps([{"key": item.key, "name": item.name, "direction": item.direction or item.tagline,
                                       "preview_asset_id": item.preview_asset_id}
                                      for item in candidates], ensure_ascii=False)),
                    images=[item["rendered_image"] for item in previews if item.get("rendered_image")],
                    usage=usage, model=settings.effective_designer_model,
                    timeout_seconds=settings.designer_page_timeout_seconds,
                )
            except Exception as error:
                logger.warning("Style preview visual review skipped: %s", error)
                raise AppError("STYLE_PREVIEW_REVIEW_FAILED", "Could not complete preview quality review",
                               "The preview gallery was withheld because its final visual review did not complete. Retry to render and review it again.",
                               502, True, action="Retry the style preview.") from error
            add_usage(usage)
            parsed = _style_preview_reviews(response, candidates)
            if parsed is not None:
                return parsed

            # A visual review can be useful even when the model adds prose or emits a
            # slightly different JSON shape. Normalize that response to the strict
            # schema without asking the model to inspect the screenshots again. Never
            # infer a pass when the original review does not make a clear decision.
            logger.warning(
                "Style preview visual review returned an unsupported format (chars=%d); attempting schema normalization",
                len(response),
            )
            normalize_usage: dict[str, int] = {}
            candidate_keys = [item.key for item in candidates]
            try:
                normalized = await self.llm.structured(
                    prompt=(
                        "Normalize the supplied visual-review response into the required JSON schema. "
                        "Preserve its judgments; do not perform a new visual review or invent a pass. "
                        "Return one review for each exact candidate key: " + json.dumps(candidate_keys) + ". "
                        "If the source does not clearly establish that a candidate passed, set ready=false "
                        "and add a short issue stating that the review result was unclear.\n\n"
                        "Original visual-review response:\n" + response
                    ),
                    schema=_StylePreviewReviewBatch,
                    max_attempts=2,
                    model=settings.effective_designer_model,
                    usage=normalize_usage,
                )
                add_usage(normalize_usage)
                return _style_preview_reviews(
                    normalized.model_dump_json(), candidates
                )
            except Exception as error:
                logger.warning("Style preview review schema normalization failed: %s", error)
                return None

        review_issues = await critique_previews()
        if review_issues is None:
            raise AppError("STYLE_PREVIEW_REVIEW_FAILED", "Could not read preview quality review",
                           "The preview gallery was withheld because the visual review returned an invalid result. Retry to render and review it again.",
                           502, True, action="Retry the style preview.")
        issues = static_issues(previews)
        for key, notes in review_issues.items():
            issues.setdefault(key, []).extend(notes)

        max_repair_rounds = 2
        for repair_round in range(max_repair_rounds):
            if not issues:
                break
            revised = await asyncio.gather(*(
                render_candidate(
                    candidate,
                    review_feedback=(
                        f"BLOCKING REPAIR ROUND {repair_round + 1}/{max_repair_rounds}. Fix every issue below "
                        "in the visible rendered result. Remove unsupported factual labels/claims; retain restrained decorative footer treatment when it adds no facts and does not crowd the screen. "
                        "Do not preserve a faulty layout just because it appears in the previous HTML. "
                        "Do not add copy to fill empty space. Recompose the affected areas if needed.\n"
                        + "\n".join(issues[candidate.key])
                    ),
                    previous_html=next(item["html"] for item in previews if item["key"] == candidate.key),
                )
                for candidate in candidates if candidate.key in issues
            ), return_exceptions=True)
            for candidate, result in zip(
                (candidate for candidate in candidates if candidate.key in issues), revised
            ):
                if isinstance(result, Exception):
                    raise AppError("STYLE_PREVIEW_REPAIR_FAILED", "Could not repair a style preview",
                                   f"Preview option '{candidate.name}' could not be repaired after quality review. The gallery was withheld; retry to generate it again.",
                                   502, True, action="Retry the style preview.") from result
                old = next(i for i, item in enumerate(previews) if item["key"] == candidate.key)
                previews[old] = result

            # Re-run deterministic layout lint and visual review after each targeted repair.
            issues = static_issues(previews)
            if issues:
                continue
            review_issues = await critique_previews()
            if review_issues is None:
                raise AppError("STYLE_PREVIEW_REVIEW_FAILED", "Could not read final preview review",
                               "The preview gallery was withheld because the final visual review returned an invalid result. Retry to render and review it again.",
                               502, True, action="Retry the style preview.")
            issues = static_issues(previews)
            for key, notes in review_issues.items():
                issues.setdefault(key, []).extend(notes)

        if issues:
            details = "; ".join(f"{key}: {', '.join(notes)}" for key, notes in issues.items())
            if static_issues(previews):
                raise AppError("STYLE_PREVIEW_QA_FAILED", "Style preview did not pass layout checks",
                               f"The gallery was withheld because mobile layout checks still fail after {max_repair_rounds} targeted repairs: {details}",
                               422, True, action="Retry the style preview after updating the screen or design direction.")
            raise AppError("STYLE_PREVIEW_REVIEW_FAILED", "Style preview did not pass visual review",
                           f"The gallery was withheld because visual review still found issues after {max_repair_rounds} targeted repairs: {details}",
                           422, True, action="Retry the style preview after adjusting the art direction.")

        await self._usage(run, total_usage, "style_previews")
        message = (f"Mình chọn **{screen.name}** làm màn hình đại diện vì nó thể hiện rõ nội dung và trải nghiệm của sản phẩm. "
                   "Ba preview giữ nguyên nội dung màn hình này nhưng trình bày theo ba hướng thị giác khác nhau. "
                   "Chọn một hướng để áp dụng cho toàn bộ các màn hình đã chốt.")
        await self._emit(run, "assistant.message", {"intent": "gather", "message": message})
        public_previews = [{key: value for key, value in item.items() if key not in {"html", "rendered_image"}}
                           for item in previews]
        await self._emit(run, "style.previews", {"screen_id": screen.id, "screen_name": screen.name,
                                                   "screen_purpose": screen.purpose, "platform": platform,
                                                   "width": width, "options": public_previews})
        brief.style_preview_shown = True
        await self.store.save_design_brief(session.id, brief)
        await self._stage(run, RunStage.FINISHED, RunStatus.COMPLETED, intent="gather", assistant_message=message)

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
                design_rules=knowledge.ui_ux_design_rules(),
                palette_rule=("A design system is imported: set `palette` to null and keep its colors."
                              if imported else "Choose them for this product; the reference palette is a starting point."),
                design_system=self._design_text(design, query),
                brief=brief.model_dump_json(exclude_defaults=True),
                style_selection=(f"{brief.style_name}: {brief.style_direction}".strip(": ")
                                 if brief.style_name or brief.style_direction else "No style selected yet."),
                visual_contract=json.dumps(brief.selected_style_contract, ensure_ascii=False),
                feedback=feedback or "None",
                context=self._history(runs + [run], first_limit=SOURCE_CHARS, limit=4000),
            ),
            schema=UiSpec,
            usage=usage,
        )
        await self._usage(run, usage, "spec")
        contract = brief.selected_style_contract or {}
        spec.selected_style_key = brief.selected_style_key
        spec.style_name = brief.style_name or ""
        spec.style_direction = brief.style_direction or spec.style_direction
        spec.visual_contract = contract
        spec.approved_brief_screens = {item.id: item.model_dump(mode="json") for item in brief.screens}
        # The selected option's tokens are authoritative unless the user imported a
        # design system, which remains the source of truth for brand tokens.
        if not imported:
            if contract.get("palette"):
                spec.design.palette = Palette.model_validate(contract["palette"])
            spec.design.heading_font = contract.get("heading_font") or spec.design.heading_font
            spec.design.body_font = contract.get("body_font") or spec.design.body_font
            spec.design.radius = contract.get("radius") or spec.design.radius
            spec.design.density = contract.get("density") or spec.design.density
            if brief.style_direction:
                spec.design.mood = brief.style_direction
        spec.style_direction = brief.style_direction or spec.style_direction
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
        built_screen_ids: set[str] = set()

        async def one(index: int, screen_id: str, ref: str | None) -> None:
            screen = spec.screen(screen_id)
            await self._emit(run, "screen.started", {"screen_id": screen_id, "name": screen.name,
                                                     "index": index, "total": len(targets)})
            current = existing.get(screen_id)
            summaries[screen_id] = await self._build_screen(
                run, session, spec, screen, design, ref, current.html if current and instruction else "", instruction)
            built_screen_ids.add(screen_id)

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
        if built_screen_ids != set(targets):
            missing = sorted(set(targets) - built_screen_ids)
            raise AppError("SCREEN_BUILD_INCOMPLETE", "Not all selected screens were rebuilt",
                           "The build did not finish every target screen: " + ", ".join(missing), 502, True,
                           action="Retry the screen build.")
        latest_screens = {item.id: item for item in await self.store.list_screens(session.id)}
        built_versions = {sid: latest_screens[sid].version for sid in targets if sid in latest_screens}
        await self._emit(run, "design.build.completed", {
            "screen_ids": targets,
            "versions": built_versions,
            "style_key": spec.selected_style_key,
            "style_name": spec.style_name,
        })
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
        contract = spec.visual_contract
        for key, label in (("composition", "Composition"), ("surface_language", "Surfaces"),
                           ("shape_language", "Shape language"), ("hero_placement", "Illustration placement")):
            if contract.get(key):
                lines.append(f"{label}: {contract[key]}")
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
        selected_asset_id = str(spec.visual_contract.get("preview_asset_id") or "")
        selected_asset = asset_by_id(selected_asset_id) if selected_asset_id and screen.visual_asset_role != "none" else None
        selected_asset_data = inline_svg(selected_asset) if selected_asset else ""
        style_asset = (
            f"Selected local illustration: {selected_asset['title']} ({selected_asset['style']}). "
            f"Role for this screen: {screen.visual_asset_role}. Use it only as a separate decorative "
            "hero/background scene, at scene scale, behind/under the UI with a legibility surface. "
            "Keep the product wordmark separate. Embed it using src=\"__DESIGNER_SELECTED_STYLE_ASSET__\"."
            if selected_asset and selected_asset_data else
            f"Selected local illustration role for this screen: {screen.visual_asset_role}. "
            "Do not introduce an unrelated stock photo or substitute an illustration for the logo."
        )
        system = self.prompts.render(
            "builder", width=width, direction=self._direction_text(spec),
            design_system=self._design_text(design, query), skill=knowledge.frontend_design_skill(),
            design_rules=knowledge.ui_ux_design_rules(), style_asset=style_asset,
        )
        usage: dict[str, int] = {}
        model = settings.effective_designer_model
        timeout = settings.designer_page_timeout_seconds

        async def save(html: str, note: str) -> str:
            html = fragment_of(html)
            if selected_asset_data:
                html = html.replace("__DESIGNER_SELECTED_STYLE_ASSET__", selected_asset_data)
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
                    screen=screen.model_dump_json(exclude_defaults=True, exclude={"must_show", "rules", "imagery", "ux_query", "states"}),
                    states="; ".join(screen.states) or "(none)",
                    must_show="; ".join(screen.must_show) or "(none)", rules="; ".join(screen.rules) or "(none)",
                    images=await self._images(screen), style_asset=style_asset, others=others,
                    ux="\n".join(f"- {u}" for u in ux), reference=ref,
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
                                         checklist=knowledge.ui_ux_design_rules() + "\n\n" + knowledge.review_checklist(),
                                         html=html,
                                         approved_screen=json.dumps(spec.approved_brief_screens.get(screen.id, {}), ensure_ascii=False),
                                         screen_spec=screen.model_dump_json(exclude_defaults=True),
                                         visual_contract=json.dumps(spec.visual_contract, ensure_ascii=False)),
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

        async def audit_scope() -> _ScreenAudit:
            audit_usage: dict[str, int] = {}
            report = await self.llm.structured(
                prompt=self.prompts.render(
                    "screen-scope-review",
                    approved_screen=json.dumps(spec.approved_brief_screens.get(screen.id, {}), ensure_ascii=False),
                    screen_spec=screen.model_dump_json(exclude_defaults=True),
                    visual_contract=json.dumps(spec.visual_contract, ensure_ascii=False),
                    visible_text=result.text,
                    html=_clip(html, 18_000),
                ),
                schema=_ScreenAudit,
                image_bytes=result.image,
                model=model,
                usage=audit_usage,
                max_attempts=2,
            )
            await self._usage(run, audit_usage, f"scope-review:{screen.id}")
            return report

        audit = await audit_scope()
        if not audit.ready:
            audit_notes = "\n".join(f"- {issue}" for issue in audit.issues)
            repair = await self.llm.generate(
                system=system,
                text=self.prompts.render(
                    "review",
                    task="Final scope/style audit repair. Fix every listed issue in the visible rendered result. "
                         "Do not add content or behavior beyond the approved screen specification.\n" + audit_notes,
                    width=width,
                    checks="- Scope/style audit failed:\n" + audit_notes,
                    checklist=knowledge.ui_ux_design_rules() + "\n\n" + knowledge.review_checklist(),
                    html=html,
                    approved_screen=json.dumps(spec.approved_brief_screens.get(screen.id, {}), ensure_ascii=False),
                    screen_spec=screen.model_dump_json(exclude_defaults=True),
                    visual_contract=json.dumps(spec.visual_contract, ensure_ascii=False),
                ),
                images=[result.image] if result.image else None,
                usage=usage,
                model=model,
                timeout_seconds=timeout,
            )
            edit = apply_reply(html, repair)
            if edit.applied:
                candidate = await self._check(edit.html, screen, width, design, session.project_id)
                if candidate[3] <= score:
                    html = await save(edit.html, "final scope/style repair")
                    result, checks, blocking, score = candidate
            audit = await audit_scope()
            if not audit.ready:
                details = "; ".join(audit.issues) or "The screen did not pass source-scope/style review."
                raise AppError(
                    "SCREEN_SCOPE_REVIEW_FAILED",
                    "Screen did not pass the approved scope and style review",
                    f"{screen.name}: {details}",
                    422,
                    True,
                    action="Retry the screen build after resolving the reported issues.",
                )
        await self._usage(run, usage, f"build:{screen.id}")
        await self._emit(run, "screen.finished", {"screen_id": screen.id})
        return screen.purpose or "Đã dựng xong."

    # ── review feedback on the final design ──
    async def targets_for(self, run: RunView, feedback: str) -> list[str]:
        spec = UiSpec.model_validate(run.specification)
        named = [s.id for s in spec.screens if s.id in feedback or s.name.lower() in feedback.lower()]
        return named or [s.id for s in spec.screens]
