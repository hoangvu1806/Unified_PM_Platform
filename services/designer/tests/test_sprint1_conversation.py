import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.core.errors import AppError
from app.models import (
    DesignBrief,
    ProjectDesignContext,
    RootDecision,
    ScreenBrief,
    StyleManifest,
    UiNode,
    UiSpecification,
)
from app.workflow.analysis import analyze_request


def _spec(name: str) -> UiSpecification:
    return UiSpecification(
        screen_name=name,
        viewport_width=1440,
        viewport_height=1200,
        summary=f"{name} specification",
        root=UiNode(id="root", kind="container", name="Root"),
    )


def test_design_brief_requires_explicit_scope_before_graph() -> None:
    brief = DesignBrief(product_description="A travel planning app")
    assert brief.missing_fields() == [
        "platforms",
        "screens",
        "scope_confirmation",
        "output_filename",
    ]


def test_root_router_retries_one_invalid_json_response() -> None:
    async def scenario() -> None:
        run = SimpleNamespace(
            id=uuid4(),
            session_id=uuid4(),
            revision=1,
            prompt="Liệt kê các màn hình trong BA package",
            screen_name="Screen",
            platform="responsive",
            style_name=None,
            specification=None,
        )
        owner = SimpleNamespace(
            store=AsyncMock(),
            events=AsyncMock(),
            llm=AsyncMock(),
            prompts=SimpleNamespace(render=lambda *args, **kwargs: "router prompt"),
            _fail=AsyncMock(),
        )
        owner.store.get_run.return_value = run
        owner.store.list_runs.return_value = []
        owner.store.get_design_brief.return_value = DesignBrief()
        owner.llm.structured.side_effect = [
            AppError(
                "LLM_OUTPUT_INVALID",
                "Invalid structured JSON",
                "expected a closing brace",
                502,
                retryable=True,
            ),
            RootDecision(intent="chat", reply="Đã đọc danh sách màn hình."),
        ]

        await analyze_request(owner, run.id, "None")

        assert owner.llm.structured.await_count == 2
        assert "compact JSON object" in owner.llm.structured.await_args.kwargs["prompt"]
        owner._fail.assert_not_awaited()

    asyncio.run(scenario())


def test_ready_brief_generates_every_screen_with_shared_context() -> None:
    async def scenario() -> None:
        screens = [ScreenBrief(name=f"Screen {index}") for index in range(1, 7)]
        brief = DesignBrief(
            product_name="Atlas",
            product_description="A collaborative travel planning app",
            platforms=["mobile", "desktop"],
            screens=screens,
            output_filename="atlas.fig",
            style_name="editorial",
            scope_confirmed=True,
        )
        run = SimpleNamespace(
            id=uuid4(),
            session_id=uuid4(),
            revision=1,
            prompt="Design the complete Atlas app",
            screen_name="Screen",
            platform="responsive",
            style_name=None,
            specification=None,
        )
        owner = SimpleNamespace(
            store=AsyncMock(),
            events=AsyncMock(),
            llm=AsyncMock(),
            prompts=SimpleNamespace(render=lambda *args, **kwargs: "prompt"),
            _fail=AsyncMock(),
        )
        owner.store.get_run.return_value = run
        owner.store.list_runs.return_value = []
        owner.store.get_design_brief.return_value = DesignBrief()
        context = ProjectDesignContext(
            product_summary="Atlas travel planner",
            visual_direction="Warm editorial maps",
            style_manifest=StyleManifest(primary_color="#14532D"),
            navigation=[screen.name for screen in screens],
        )
        owner.llm.structured.side_effect = [
            RootDecision(intent="start_design", reply="Generating all screens.", brief=brief),
            context,
        ]

        generator = AsyncMock(side_effect=[_spec(screen.name) for screen in screens])
        with patch(
            "app.workflow.analysis.generate_ui_specification",
            generator,
        ):
            await analyze_request(owner, run.id, "None")

        assert generator.await_count == 6
        calls = generator.await_args_list
        assert [call.kwargs["screen_name"] for call in calls] == [screen.name for screen in screens]
        assert all(call.kwargs["style_manifest"] == context.style_manifest for call in calls)
        assert len({call.kwargs["project_context"] for call in calls}) == 1
        project = owner.store.set_artifact.await_args.args[3]
        assert len(project["screens"]) == 6
        assert project["brief"]["output_filename"] == "atlas.fig"
        owner._fail.assert_not_awaited()

    asyncio.run(scenario())
