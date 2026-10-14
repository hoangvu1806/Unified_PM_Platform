import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.prompts import PromptLibrary
from app.generation.adk_hierarchical import generate_ui_specification
from app.models import (
    PageSkeleton,
    SectionPlan,
    SectionUiNode,
    StyleManifest,
    UiNode,
    UiSpecification,
)


def test_style_manifest_defaults() -> None:
    manifest = StyleManifest()
    assert manifest.primary_color == "#2563EB"
    assert manifest.accent_color == "#F59E0B"
    assert manifest.accent_gold == "#F59E0B"
    assert manifest.canvas_background == "#F8FAFC"
    assert manifest.corner_radius == 12


def test_style_manifest_uses_canonical_accent_and_accepts_legacy_or_null() -> None:
    legacy = StyleManifest.model_validate({"accent_gold": "#C2410C"})
    fallback = StyleManifest.model_validate({"accent_color": None})
    schema = PageSkeleton.model_json_schema()["$defs"]["StyleManifest"]["properties"]

    assert legacy.accent_color == "#C2410C"
    assert legacy.model_dump(by_alias=True)["accent_color"] == "#C2410C"
    assert fallback.accent_color == "#F59E0B"
    assert "accent_color" in schema
    assert "accent_gold" not in schema


def test_page_skeleton_validation() -> None:
    skeleton = PageSkeleton(
        screen_name="Landing Page 2/9",
        platform="desktop",
        viewport_width=1440,
        viewport_height=3600,
        summary="National Celebration Landing Page",
        style_manifest=StyleManifest(primary_color="#DC2626"),
        sections=[
            SectionPlan(
                id="sec_header",
                role="header",
                name="Navbar",
                intent="Sticky navigation bar",
            ),
            SectionPlan(
                id="sec_hero",
                role="hero",
                name="Hero Banner",
                intent="High impact celebration hero",
            ),
        ],
    )
    assert len(skeleton.sections) == 2
    assert skeleton.sections[0].role == "header"
    assert skeleton.style_manifest.primary_color == "#DC2626"


def test_page_skeleton_requires_at_least_one_section() -> None:
    with pytest.raises(ValidationError):
        PageSkeleton(
            screen_name="Invalid Screen",
            summary="Empty sections must fail",
            sections=[],
        )


def test_failed_section_is_not_replaced_with_fake_successful_content() -> None:
    async def scenario():
        llm = AsyncMock()
        llm.structured.side_effect = [
            PageSkeleton(
                screen_name="Orders",
                summary="Orders",
                sections=[SectionPlan(id="orders", name="Orders", intent="Review orders")],
            ),
            RuntimeError("Model unavailable"),
        ]
        with pytest.raises(RuntimeError, match="Model unavailable"):
            await generate_ui_specification(
                llm,
                PromptLibrary(),
                user_request="Design orders",
                screen_name="Orders",
            )

    asyncio.run(scenario())


def test_hard_constraints_are_carried_from_skeleton_to_specification() -> None:
    async def scenario():
        llm = AsyncMock()
        llm.structured.side_effect = [
            PageSkeleton(
                screen_name="Checkout",
                summary="Checkout",
                hard_constraints=["Exactly 3 payment methods", "Primary CTA at bottom right"],
                sections=[SectionPlan(id="payment", name="Payment", intent="Choose payment")],
            ),
            UiSpecification(
                screen_name="Checkout",
                summary="Checkout",
                viewport_width=1440,
                viewport_height=1024,
                root=UiNode(id="root", kind="container", name="Checkout"),
            ),
        ]
        result = await generate_ui_specification(
            llm,
            PromptLibrary(),
            user_request="Design checkout",
            screen_name="Checkout",
        )
        assert result.hard_constraints == ["Exactly 3 payment methods", "Primary CTA at bottom right"]

    asyncio.run(scenario())


def test_section_ui_node_compatibility_with_ui_node() -> None:
    sec = SectionUiNode(
        id="sec_hero",
        name="Hero Section",
        children=[
            UiNode(
                id="hero_title",
                kind="text",
                name="Hero Title",
                content={"text": "Tự Hào Non Sông", "type": "heading", "level": 1},
            ),
            UiNode(
                id="hero_cta",
                kind="component",
                name="CTA Button",
                content={"text": "Đặt Mua Ngay"},
                requirement={"role": "button", "variant_intent": "primary"},
            ),
        ],
    )

    root = UiNode(
        id="page_root",
        kind="container",
        name="Root Page",
        children=[
            UiNode(
                id=sec.id,
                kind="container",
                name=sec.name,
                layout=sec.layout,
                children=sec.children,
            )
        ],
    )

    spec = UiSpecification(
        schema_version="2.0",
        screen_name="Test Screen",
        platform="desktop",
        viewport_width=1440,
        viewport_height=2400,
        summary="A test screen",
        root=root,
    )

    assert len(spec.root.children) == 1
    hero = spec.root.children[0]
    assert hero.id == "sec_hero"
    assert len(hero.children) == 2
    assert hero.children[0].content["text"] == "Tự Hào Non Sông"


def test_prompts_master_architect_and_screen_composer_exist() -> None:
    prompts = PromptLibrary()
    rendered_architect = prompts.render(
        "master_architect",
        user_request="Test Request",
        screen_name="Test Screen",
        platform="desktop",
        conversation_history="[]",
        revision_feedback="None",
    )
    assert "Chief Product & UI Architect" in rendered_architect
    assert "PageSkeleton" in rendered_architect
    assert "shared destinations" in rendered_architect

    rendered_worker = prompts.render(
        "screen-composer",
        user_request="Test Request",
        skeleton="{}",
        project_context="{}",
        conversation_history="[]",
        revision_feedback="None",
    )
    assert "COMPOSE THE WHOLE SCREEN" in rendered_worker
    assert "UiSpecification" in rendered_worker


def test_hierarchical_generator_e2e_with_mock_llm() -> None:
    async def _test() -> None:
        mock_llm = AsyncMock()
        prompts = PromptLibrary()

        # Mock Master Architect returning skeleton
        skeleton_resp = PageSkeleton(
            screen_name="Test Product Landing",
            platform="desktop",
            viewport_width=1440,
            viewport_height=3200,
            summary="A test celebration page",
            style_manifest=StyleManifest(primary_color="#DC2626"),
            sections=[
                SectionPlan(
                    id="sec_header",
                    role="header",
                    name="Header Nav",
                    intent="Sticky navigation",
                ),
                SectionPlan(
                    id="sec_hero",
                    role="hero",
                    name="Hero Banner",
                    intent="Hero visual display",
                    composition="Offset editorial split with the action crossing the media edge",
                    visual_anchor="A live product preview",
                    component_treatment="Pair the real search input and action as one command surface",
                ),
            ],
        )

        composed = UiSpecification(
            screen_name="Test Product Landing",
            platform="desktop",
            viewport_width=1440,
            viewport_height=3200,
            summary="A test celebration page",
            root=UiNode(
                id="draft-root",
                kind="container",
                name="Draft",
                children=[
                    UiNode(
                        id="sec_header",
                        kind="container",
                        name="Header Nav",
                        children=[UiNode(id="logo", kind="text", name="Logo", content={"text": "Brand"})],
                    ),
                    UiNode(
                        id="sec_hero",
                        kind="container",
                        name="Hero Banner",
                        children=[UiNode(id="hero_h1", kind="text", name="Heading", content={"text": "Welcome"})],
                    ),
                ],
            ),
        )

        def side_effect(prompt: str, schema: type, **_kwargs: Any) -> Any:
            if schema == PageSkeleton:
                return skeleton_resp
            if schema == UiSpecification:
                return composed
            raise ValueError(f"Unexpected schema {schema}")

        mock_llm.structured.side_effect = side_effect

        skeleton_events = []
        section_events = []

        async def on_skeleton(sk: PageSkeleton) -> None:
            skeleton_events.append(sk)

        async def on_section(sec: SectionUiNode, cur: int, tot: int) -> None:
            section_events.append((sec.id, cur, tot))

        spec = await generate_ui_specification(
            mock_llm,
            prompts,
            user_request="Design landing page",
            screen_name="Test Product Landing",
            platform="desktop",
            on_skeleton=on_skeleton,
            on_section=on_section,
        )

        assert isinstance(spec, UiSpecification)
        assert spec.screen_name == "Test Product Landing"
        assert spec.root.kind == "container"
        assert len(spec.root.children) == 2
        assert spec.root.children[0].id == "sec_header"
        assert spec.root.children[1].id == "sec_hero"
        assert spec.root.children[1].content["visual_anchor"] == "A live product preview"
        assert "command surface" in spec.root.children[1].content["component_treatment"]

        assert len(skeleton_events) == 1
        assert skeleton_events[0].screen_name == "Test Product Landing"

        assert len(section_events) == 2
        assert section_events[0] == ("sec_header", 1, 2)
        assert section_events[1] == ("sec_hero", 2, 2)

    asyncio.run(_test())


def test_responsive_skeleton_uses_desktop_reference_canvas() -> None:
    async def scenario() -> None:
        skeleton = PageSkeleton(
            screen_name="Operations",
            platform="responsive",
            viewport_width=390,
            viewport_height=844,
            summary="Responsive operations",
            sections=[SectionPlan(id="content", name="Content", intent="Show operations")],
        )
        composed = UiSpecification(
            screen_name="Operations",
            platform="responsive",
            viewport_width=390,
            viewport_height=844,
            summary="Responsive operations",
            root=UiNode(
                id="root",
                kind="container",
                name="Operations",
                children=[UiNode(id="content", kind="container", name="Content")],
            ),
        )
        llm = SimpleNamespace(structured=AsyncMock(side_effect=[skeleton, composed]))

        result = await generate_ui_specification(
            llm,
            PromptLibrary(),
            user_request="Responsive enterprise app",
            screen_name="Operations",
            platform="responsive",
        )

        assert (result.viewport_width, result.viewport_height) == (1440, 1024)

    asyncio.run(scenario())


def test_composer_section_count_can_differ_from_skeleton() -> None:
    async def scenario() -> None:
        skeleton = PageSkeleton(
            screen_name="Login",
            platform="mobile",
            viewport_width=390,
            viewport_height=844,
            summary="Login screen",
            sections=[SectionPlan(id="login", name="Login", intent="Authenticate the user")],
        )
        composed = UiSpecification(
            screen_name="Login",
            platform="mobile",
            viewport_width=390,
            viewport_height=844,
            summary="Login screen",
            root=UiNode(
                id="root",
                kind="container",
                name="Login",
                children=[
                    UiNode(id="brand", kind="container", name="Brand"),
                    UiNode(id="form", kind="container", name="Form"),
                    UiNode(id="support", kind="container", name="Support"),
                ],
            ),
        )
        llm = SimpleNamespace(structured=AsyncMock(side_effect=[skeleton, composed]))

        result = await generate_ui_specification(
            llm,
            PromptLibrary(),
            user_request="Design a login screen",
            screen_name="Login",
            platform="mobile",
        )

        assert [node.id for node in result.root.children] == ["login", "form", "support"]

    asyncio.run(scenario())


def test_get_color_tokens_and_palette_jsx() -> None:
    from app.generation.jsx import compile_palette_jsx, get_color_tokens

    custom_style = StyleManifest(
        primary_color="#059669",
        primary_dark="#047857",
        accent_color="#F97316",
        neutral_dark="#111827",
        neutral_body="#4B5563",
        canvas_background="#F9FAFB",
    )
    tokens = get_color_tokens(custom_style)
    token_dict = {name: val for name, val, _, _ in tokens}
    assert token_dict["brand/primary"] == "#059669"
    assert token_dict["accent/color"] == "#F97316"
    assert token_dict["neutral/dark"] == "#111827"

    palette_jsx = compile_palette_jsx("Fintech Dashboard", custom_style)
    assert "#059669" in palette_jsx
    assert "#F97316" in palette_jsx
    assert "LLM Authored Tokens" in palette_jsx
    assert "Fintech Dashboard" in palette_jsx
