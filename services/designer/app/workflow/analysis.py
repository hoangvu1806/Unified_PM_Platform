import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from ..core.errors import AppError, unwrap_app_error
from ..core.config import designer_asset_file
from ..core.logger import log_agent_error
from ..generation.adk_hierarchical import generate_ui_specification
from ..models import (
    DesignBrief,
    PageSkeleton,
    ProjectDesignContext,
    ProjectSpecification,
    RootDecision,
    RunStage,
    RunStatus,
    ScreenBrief,
    ScreenSpecification,
    SectionUiNode,
)
from .workspace_agent import handle_workspace_message


def _conversation_context(previous: list[Any]) -> str:
    """Keep useful conversational context without full specifications."""
    turns: list[dict[str, Any]] = []
    for item in reversed(previous):
        user_prompt = item.prompt
        attachment_marker = "<!-- DESIGNER_ATTACHMENT_CONTEXT -->"
        if attachment_marker in user_prompt and getattr(item, "intent", None):
            user_prompt = user_prompt.split(attachment_marker, 1)[0].strip()
            user_prompt += "\n[Parsed attachment is already captured in the session brief.]"
        turn: dict[str, Any] = {
            "user": user_prompt,
            "assistant": item.assistant_message or "",
            "intent": item.intent,
        }
        for field in ("style_name", "screen_name", "platform"):
            value = getattr(item, field, None)
            if value:
                turn[field] = value
        specification = getattr(item, "specification", None)
        if specification is not None:
            summary = getattr(specification, "summary", None)
            if summary:
                turn["specification_summary"] = summary
        turns.append(turn)
    return json.dumps(turns, ensure_ascii=False) if turns else "[]"


def _merge_brief(current: DesignBrief, proposed: DesignBrief) -> DesignBrief:
    """Merge a router snapshot without erasing facts learned earlier."""
    screens = list(current.screens)
    positions: dict[str, int] = {}
    for index, screen in enumerate(screens):
        key = screen.id.casefold() or " ".join(screen.name.casefold().split())
        positions[key] = index
    for screen in proposed.screens:
        key = screen.id.casefold() or " ".join(screen.name.casefold().split())
        if key in positions:
            screens[positions[key]] = screen
        else:
            positions[key] = len(screens)
            screens.append(screen)
    return DesignBrief(
        product_name=proposed.product_name.strip() or current.product_name,
        product_description=(proposed.product_description.strip() or current.product_description),
        platforms=proposed.platforms or current.platforms,
        screens=screens,
        output_filename=proposed.output_filename or current.output_filename,
        style_name=proposed.style_name or current.style_name,
        design_system_ids=proposed.design_system_ids or current.design_system_ids,
        scope_confirmed=proposed.scope_confirmed or current.scope_confirmed,
    )


def _build_scope(merged: DesignBrief, proposed: DesignBrief, requested_screen_ids: list[str]) -> DesignBrief:
    """Select screens for this run while retaining the complete session inventory."""
    wanted = {item.casefold() for item in requested_screen_ids if item.strip()}
    if wanted:
        screens = [
            screen
            for screen in merged.screens
            if screen.id.casefold() in wanted
            or any(source_id.casefold() in wanted for source_id in screen.source_ui_ids)
        ]
    elif proposed.screens:
        proposed_keys = {
            screen.id.casefold() or " ".join(screen.name.casefold().split()) for screen in proposed.screens
        }
        screens = [
            screen
            for screen in merged.screens
            if (screen.id.casefold() or " ".join(screen.name.casefold().split())) in proposed_keys
        ]
    else:
        screens = list(merged.screens)
    return merged.model_copy(deep=True, update={"screens": screens or merged.screens})


def _apply_run_hints(brief: DesignBrief, run: Any) -> DesignBrief:
    value = brief.model_copy(deep=True)
    if not value.style_name and getattr(run, "style_name", None):
        value.style_name = run.style_name
    platform = getattr(run, "platform", None)
    if not value.platforms and platform and platform != "responsive":
        value.platforms = [platform]
    screen_name = getattr(run, "screen_name", "")
    if not value.screens and screen_name not in {"", "Screen", "New screen"}:
        value.screens = [ScreenBrief(name=screen_name, platforms=value.platforms)]
    return value


async def analyze_request(owner: Any, run_id: UUID, feedback: str) -> None:
    run = await owner.store.get_run(run_id)
    if run is None:
        return
    try:
        await owner.store.update_run(run.id, stage=RunStage.REQUIREMENT, status=RunStatus.RUNNING)
        await owner.events.emit(
            run.id,
            run.revision,
            "stage.changed",
            {"stage": "requirement", "message": "Understanding your message"},
        )
        previous = [item for item in await owner.store.list_runs(run.session_id) if item.id != run.id][:8]
        history = _conversation_context(previous)
        stored_brief = await owner.store.get_design_brief(run.session_id)
        if not isinstance(stored_brief, DesignBrief):
            stored_brief = DesignBrief()
        current_brief = _apply_run_hints(stored_brief, run)
        if await handle_workspace_message(owner, run, conversation_history=history):
            return
        router_prompt = owner.prompts.render(
            "router",
            user_request=run.prompt,
            conversation_history=history,
            current_brief=current_brief.model_dump_json(indent=2),
        )
        try:
            decision = await owner.llm.structured(
                prompt=router_prompt,
                schema=RootDecision,
            )
        except AppError as error:
            if error.code != "LLM_OUTPUT_INVALID":
                raise
            decision = await owner.llm.structured(
                prompt=(
                    f"{router_prompt}\n\nThe previous response failed JSON validation. "
                    "Return the same decision again as one complete, "
                    "compact JSON object. Use a concise reply and do not omit closing "
                    "quotes, brackets, or braces."
                ),
                schema=RootDecision,
            )

        if decision.intent == "chat":
            await _finish_conversation(owner, run, "chat", decision.reply)
            return

        brief = _merge_brief(current_brief, decision.brief)
        if not brief.output_filename and brief.product_name:
            brief.output_filename = f"{brief.product_name}.fig"
        await owner.store.save_design_brief(run.session_id, brief)
        missing = brief.missing_fields()
        if decision.intent != "start_design" or missing:
            await _finish_conversation(
                owner,
                run,
                "clarify_design",
                decision.reply,
                screen_name=brief.product_name or None,
                platform=_platform_label(brief.platforms),
                style_name=brief.style_name,
            )
            return

        build_scope = _build_scope(brief, decision.brief, decision.requested_screen_ids)
        await _generate_project(owner, run, build_scope, history, feedback, decision.reply)
    except Exception as error:
        log_agent_error("workflow_analysis", f"Analysis error on run {run.id} rev {run.revision}", error)
        app_err = unwrap_app_error(error)
        failure = app_err or AppError(
            "WORKFLOW_FAILED",
            "Workflow failed",
            str(error) or repr(error),
            500,
            True,
        )
        await owner._fail(run.id, run.revision, failure)


async def _finish_conversation(
    owner: Any,
    run: Any,
    intent: str,
    reply: str,
    *,
    screen_name: str | None = None,
    platform: str | None = None,
    style_name: str | None = None,
) -> None:
    await owner.store.update_run(
        run.id,
        stage=RunStage.FINISHED,
        status=RunStatus.COMPLETED,
        intent=intent,
        assistant_message=reply,
        screen_name=screen_name,
        platform=platform,
        style_name=style_name,
    )
    await owner.events.emit(run.id, run.revision, "assistant.message", {"message": reply})


async def _generate_project(
    owner: Any,
    run: Any,
    brief: DesignBrief,
    history: str,
    feedback: str,
    reply: str,
) -> None:
    exact_assets = await owner.store.get_artifact(run.id, run.revision, "exact_assets") or []
    if not exact_assets:
        exact_assets = await owner.store.get_latest_session_artifact(
            run.session_id, "exact_assets"
        ) or []
        if exact_assets:
            await owner.store.set_artifact(
                run.id, run.revision, "exact_assets", exact_assets
            )
    asset_context = ""
    image_bytes = None
    image_mime_type = "image/jpeg"
    if exact_assets:
        asset_context = (
            "\n\nEXACT ASSETS (must use the original uploaded files; only resize, reposition, crop, "
            "or permitted display styling). IMPORTANT: an upload is opt-in, not a global overlay. "
            "Use an asset on this screen only when the user's request or this screen's purpose "
            "explicitly asks for it. If it is requested, set the selected node's content.asset_id "
            "to the exact asset ID. Do not add the asset to other screens merely because it was uploaded.\n"
            + json.dumps(exact_assets, ensure_ascii=False)
        )
        first = exact_assets[0] if isinstance(exact_assets[0], dict) else {}
        asset_id = str(first.get("id") or "")
        asset_file = designer_asset_file(asset_id)
        if asset_file.is_file():
            image_bytes = asset_file.read_bytes()
            image_mime_type = str(first.get("mime_type") or image_mime_type)
    style_name = brief.style_name or "custom"
    await owner.store.update_run(
        run.id,
        stage=RunStage.SPECIFICATION,
        status=RunStatus.RUNNING,
        intent="start_design",
        assistant_message=reply,
        screen_name=brief.product_name or brief.output_filename.removesuffix(".fig"),
        platform=_platform_label(brief.platforms),
        style_name=style_name,
    )
    await owner.events.emit(run.id, run.revision, "assistant.message", {"message": reply})
    await owner.events.emit(
        run.id,
        run.revision,
        "stage.changed",
        {
            "stage": "specification",
            "message": f"Planning {len(brief.screens)} screens",
        },
    )

    designer_model = getattr(getattr(owner.llm, "settings", None), "effective_designer_model", None)
    if not isinstance(designer_model, str):
        designer_model = None
    design_context = await owner.llm.structured(
        prompt=owner.prompts.render(
            "project_analyzer",
            user_request=run.prompt,
            design_brief=brief.model_dump_json(indent=2),
            conversation_history=history,
            revision_feedback=feedback,
        ),
        schema=ProjectDesignContext,
        **({"model": designer_model} if designer_model else {}),
    )
    screen_specs: list[ScreenSpecification] = []
    total = len(brief.screens)
    project_context_json = design_context.model_dump_json(indent=2)

    for index, screen in enumerate(brief.screens, start=1):
        platforms = screen.platforms or brief.platforms
        platform = platforms[0] if len(platforms) == 1 else "responsive"

        async def on_skeleton_ready(
            skeleton: PageSkeleton,
            *,
            current: int = index,
            screen_id: str = screen.id,
            screen_name: str = screen.name,
        ) -> None:
            await owner.events.emit(
                run.id,
                run.revision,
                "screen.skeleton_ready",
                {
                    "screen_id": screen_id,
                    "screen_name": skeleton.screen_name,
                    "current": current,
                    "total": total,
                    "sections": [item.name for item in skeleton.sections],
                    "message": f"Planned {screen_name} ({current}/{total})",
                },
            )

        async def on_section_ready(
            section: SectionUiNode,
            current: int,
            section_total: int,
            *,
            screen_id: str = screen.id,
            screen_name: str = screen.name,
        ) -> None:
            await owner.events.emit(
                run.id,
                run.revision,
                "screen.section_ready",
                {
                    "screen_id": screen_id,
                    "section_id": section.id,
                    "progress": f"{current}/{section_total}",
                    "message": f"Expanded {screen_name}: {section.name}",
                },
            )

        specification = await generate_ui_specification(
            owner.llm,
            owner.prompts,
            user_request=(f"{brief.product_description}\n\nScreen: {screen.name}\nPurpose: {screen.purpose}{asset_context}"),
            screen_name=screen.name,
            platform=platform,
            style_manifest=design_context.style_manifest,
            project_context=project_context_json,
            conversation_history=history,
            revision_feedback=feedback,
            on_skeleton=on_skeleton_ready,
            on_section=on_section_ready,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
        )
        screen_specs.append(
            ScreenSpecification(
                screen_id=screen.id,
                platforms=platforms,
                specification=specification,
            )
        )
        await owner.events.emit(
            run.id,
            run.revision,
            "screen.specification_ready",
            {
                "screen_id": screen.id,
                "current": index,
                "total": total,
                "message": f"Completed specification for {screen.name}",
            },
        )

    project = ProjectSpecification(brief=brief, design_context=design_context, screens=screen_specs)
    await owner.store.set_artifact(
        run.id,
        run.revision,
        "project_specification",
        project.model_dump(mode="json"),
    )
    primary = screen_specs[0].specification
    await owner.store.update_run(
        run.id,
        stage=RunStage.REVIEW_SPEC,
        status=RunStatus.WAITING_REVIEW,
        specification=primary,
    )
    await owner.events.emit(
        run.id,
        run.revision,
        "project.specification_ready",
        {
            "screen_count": len(screen_specs),
            "platforms": brief.platforms,
            "message": f"{len(screen_specs)} screen specifications are ready for review.",
        },
    )
    await owner.events.emit(
        run.id,
        run.revision,
        "review.required",
        {
            "checkpoint": "specification",
            "message": "Review the complete project scope and screen specifications.",
        },
    )


def _platform_label(platforms: Sequence[str]) -> str | None:
    if not platforms:
        return None
    return platforms[0] if len(platforms) == 1 else "responsive"
