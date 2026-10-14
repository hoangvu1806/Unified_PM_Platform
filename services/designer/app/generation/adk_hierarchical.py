"""Creative skeleton followed by one coherent whole-screen semantic composition."""

from collections.abc import Callable, Coroutine
from typing import Any

from ..core.llm import AdkProvider
from ..core.prompts import PromptLibrary
from ..models import PageSkeleton, SectionUiNode, StyleManifest, UiSpecification


async def generate_ui_specification(
    llm: AdkProvider,
    prompts: PromptLibrary,
    *,
    user_request: str,
    screen_name: str,
    platform: str = "responsive",
    style_manifest: StyleManifest | None = None,
    project_context: str = "{}",
    conversation_history: str = "[]",
    revision_feedback: str = "None",
    on_skeleton: Callable[[PageSkeleton], Coroutine[Any, Any, None]] | None = None,
    on_section: Callable[[SectionUiNode, int, int], Coroutine[Any, Any, None]] | None = None,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
) -> UiSpecification:
    """Generate the required skeleton, then compose the whole screen in one call."""
    designer_model = getattr(getattr(llm, "settings", None), "effective_designer_model", None)
    if not isinstance(designer_model, str):
        designer_model = None
    skeleton = await llm.structured(
        prompt=prompts.render(
            "master_architect",
            user_request=user_request,
            screen_name=screen_name,
            platform=platform,
            project_context=project_context,
            conversation_history=conversation_history,
            revision_feedback=revision_feedback,
        ),
        schema=PageSkeleton,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
        **({"model": designer_model} if designer_model else {}),
    )
    if style_manifest is not None:
        skeleton.style_manifest = style_manifest
    if platform == "responsive":
        # OpenPencil pages are static frames. Use the desktop reference canvas
        # for a responsive product and let the composition express adaptation;
        # explicit mobile/tablet requests keep their own viewport.
        skeleton.platform = "responsive"
        skeleton.viewport_width = 1440
        skeleton.viewport_height = 1024
    if on_skeleton:
        await on_skeleton(skeleton)
    composition_prompt = prompts.render(
        "screen-composer",
        user_request=user_request,
        skeleton=skeleton.model_dump_json(indent=2),
        project_context=project_context,
        conversation_history=conversation_history,
        revision_feedback=revision_feedback,
    )
    specification = await llm.structured(
        prompt=composition_prompt,
        schema=UiSpecification,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
        **({"model": designer_model} if designer_model else {}),
    )
    specification.screen_name = skeleton.screen_name
    specification.platform = skeleton.platform
    specification.viewport_width = skeleton.viewport_width
    specification.viewport_height = skeleton.viewport_height
    specification.summary = skeleton.summary
    specification.style_manifest = skeleton.style_manifest
    # Preserve the architect's contract through the composition model.
    specification.hard_constraints = list(skeleton.hard_constraints)
    specification.root.id = "root_canvas"
    specification.root.name = skeleton.screen_name
    planned_by_id = {section.id: section for section in skeleton.sections}
    used_plan_ids: set[str] = set()
    composed_sections = specification.root.children
    for index, node in enumerate(composed_sections, 1):
        section = planned_by_id.get(node.id)
        if section is None and index <= len(skeleton.sections):
            section = skeleton.sections[index - 1]
        if section is not None and section.id not in used_plan_ids:
            node.id = section.id
            used_plan_ids.add(section.id)
            node.content.update(
                intent=section.intent,
                composition=section.composition,
                visual_anchor=section.visual_anchor,
                component_treatment=section.component_treatment,
            )
        elif not node.id.strip():
            node.id = f"section_{index}"
        node.kind = "container"
        if on_section:
            await on_section(
                SectionUiNode(id=node.id, name=node.name, layout=node.layout, children=node.children),
                index,
                len(composed_sections),
            )
    return specification
