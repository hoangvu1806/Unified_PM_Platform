from pathlib import Path

from app.core.prompts import PromptLibrary

RUNTIME_PROMPTS = {
    "page-designer",
    "delivery",
    "master_architect",
    "project_analyzer",
    "resolver",
    "revision",
    "router",
    "screen-composer",
    "workspace-page-plan",
    "workspace-router",
}


def test_runtime_prompt_inventory_has_no_legacy_templates() -> None:
    directory = Path(__file__).resolve().parents[1] / "prompts"
    actual = {path.stem for path in directory.glob("*.md")}
    assert actual == RUNTIME_PROMPTS
    library = PromptLibrary(directory)
    assert all(library._load(name) for name in RUNTIME_PROMPTS)


def test_router_groups_ba_touchpoints_without_losing_traceability() -> None:
    directory = Path(__file__).resolve().parents[1] / "prompts"
    router = PromptLibrary(directory)._load("router")

    assert "UI screens to design" in router
    assert "not as a one-to-one screen list" in router
    assert "source_ui_ids" in router
    assert "Every valid UIT" in router
    assert "UIT-02 -> UIT-05" in router
    assert "resulting physical screen list" in router


def test_page_designer_requires_live_reflection_before_finish() -> None:
    directory = Path(__file__).resolve().parents[1] / "prompts"
    prompt = PromptLibrary(directory)._load("page-designer")

    assert "inspect_page" in prompt
    assert "live JSX" in prompt
    assert "latest screenshot" in prompt
    assert "reflect_page" in prompt
    assert "project navigation" in prompt
    assert "inspect_nodes" in prompt
    assert "edit_canvas" in prompt
    assert "canvas_progress" in prompt


def test_design_knowledge_is_injected_into_design_prompts() -> None:
    directory = Path(__file__).resolve().parents[1] / "prompts"
    library = PromptLibrary(directory)

    prompt = library.render(
        "screen-composer",
        user_request="Design a project analytics dashboard.",
    )

    assert "# Login Screen Design Knowledge" in prompt
    assert "# Design craft: evidence, direction, execution" in prompt
    assert "# Layout and typography rules" in prompt
    assert "User-facing text must wrap" in prompt
