from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.llm import parse_structured_output
from app.models import (
    ComponentBinding,
    ComponentBindingSet,
    ComponentCandidate,
    ConversationDecision,
    OpenPencilProfile,
    UiSpecification,
)
from app.openpencil.binding import validate_bindings
from app.workflow.analysis import _conversation_context


def test_ui_specification_accepts_recursive_nodes() -> None:
    spec = UiSpecification.model_validate(
        {
            "screen_name": "Home",
            "platform": "mobile",
            "viewport_width": 390,
            "viewport_height": 844,
            "summary": "A focused storefront",
            "root": {
                "id": "home",
                "kind": "container",
                "name": "Page",
                "children": [{"id": "hero-title", "kind": "text", "name": "Hero title"}],
            },
        }
    )

    assert spec.root.children[0].id == "hero-title"


def test_structured_output_accepts_json_code_fence() -> None:
    content = """```json
{"screen_name":"Home","platform":"mobile","viewport_width":390,"viewport_height":844,"summary":"Store","root":{"id":"home","kind":"container","name":"Page","children":[]}}
```"""
    specification = parse_structured_output(content, UiSpecification)
    assert specification.screen_name == "Home"


def test_conversation_router_accepts_normal_chat() -> None:
    decision = parse_structured_output(
        '```json\n{"intent":"chat","reply":"Xin chào! Tôi có thể giúp gì cho bạn?"}\n```',
        ConversationDecision,
    )
    assert decision.intent == "chat"


def test_openpencil_profile_requires_frontend_values() -> None:
    with pytest.raises(ValidationError):
        OpenPencilProfile(endpoint="", source_file="", output_file="")
    with pytest.raises(ValidationError):
        OpenPencilProfile(
            endpoint="localhost:7600/mcp",
            source_file="system.fig",
            output_file="screen.fig",
        )
    with pytest.raises(ValidationError):
        OpenPencilProfile(
            endpoint="http://mcp.example/mcp",
            source_file="system.fig",
            output_file="system.fig",
        )


def test_binding_uses_inspected_metadata_as_source_of_truth() -> None:
    candidate = ComponentCandidate(
        component_id="button:1",
        library_id="TapTap Design System",
        name="Primary",
        canonical_path="Button/Primary",
        variant_name="Size=Default",
        text_slots=["text:Text"],
    )
    proposed = ComponentBindingSet(
        bindings=[
            ComponentBinding(
                node_id="buy",
                status="resolved",
                component_id="button:1",
                library_id="taptap",
                canonical_path="wrong/path",
                selected_variant="invented",
                text_values={"text": "Mua ngay"},
            )
        ]
    )

    result = validate_bindings([{"node_id": "buy"}], [candidate], proposed)

    assert result.bindings[0].library_id == "TapTap Design System"
    assert result.bindings[0].canonical_path == "Button/Primary"
    assert result.bindings[0].selected_variant == "Size=Default"
    assert result.bindings[0].text_values == {"text:Text": "Mua ngay"}


def test_unknown_binding_becomes_layout_fallback() -> None:
    proposed = ComponentBindingSet(
        bindings=[
            ComponentBinding(
                node_id="product",
                status="resolved",
                component_id="invented",
            )
        ]
    )

    result = validate_bindings([{"node_id": "product"}], [], proposed)

    assert result.bindings[0].status == "unresolved"


def test_conversation_context_keeps_previous_design_request() -> None:
    previous = [
        SimpleNamespace(
            prompt="Thiết kế landing page bán cờ Việt Nam cho ngày 2/9",
            assistant_message="Tôi sẽ thiết kế landing page.",
            intent="design",
            specification=SimpleNamespace(
                screen_name="Flag store",
                platform="responsive",
                summary="Vietnamese flag storefront",
            ),
        )
    ]

    context = _conversation_context(previous)

    assert "landing page bán cờ Việt Nam" in context
    assert "Vietnamese flag storefront" in context


def test_analyze_request_design_flow() -> None:
    import asyncio
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.models import (
        ConversationDecision,
        PageSkeleton,
        SectionPlan,
        SectionUiNode,
        StyleManifest,
        UiNode,
    )
    from app.workflow.analysis import analyze_request

    run_id = uuid4()
    mock_run = SimpleNamespace(
        id=run_id,
        session_id=uuid4(),
        revision=1,
        prompt="Design a university landing page",
        screen_name="University Landing",
        platform="desktop",
        specification=None,
    )

    owner = SimpleNamespace(
        store=AsyncMock(),
        events=AsyncMock(),
        llm=AsyncMock(),
        prompts=SimpleNamespace(render=lambda *a, **kw: "Mock Prompt"),
    )
    owner.store.get_run.return_value = mock_run
    owner.store.list_runs.return_value = []

    # Mock conversation decision: design
    owner.llm.structured.side_effect = [
        ConversationDecision(intent="design", reply="Sure, designing landing page."),
        PageSkeleton(
            screen_name="University Landing",
            summary="A university landing page",
            style_manifest=StyleManifest(),
            sections=[
                SectionPlan(id="sec_hero", role="hero", name="Hero Section", intent="Hero showcase"),
            ],
        ),
        SectionUiNode(
            id="sec_hero",
            name="Hero Section",
            children=[UiNode(id="h1", kind="text", name="Title", content={"text": "University"})],
        ),
    ]

    asyncio.run(analyze_request(owner, run_id, "None"))

    owner.events.emit.assert_any_call(
        run_id, 1, "assistant.message", {"message": "Sure, designing landing page."}
    )
    owner.store.update_run.assert_called()


