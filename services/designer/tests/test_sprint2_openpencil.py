import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.errors import AppError
from app.models import (
    ComponentBinding,
    ComponentBindingSet,
    ComponentRequirement,
    DesignBrief,
    OpenPencilProfile,
    ProjectDesignContext,
    ProjectSpecification,
    ScreenBrief,
    ScreenSpecification,
    UiNode,
    UiSpecification,
)
from app.openpencil.gateway import OpenPencilGateway
from app.openpencil.project_executor import (
    _prepare_project_document,
    assemble_project,
    binding_subset,
    page_name,
    specification_for_platform,
)


def specification(platform: str = "mobile") -> UiSpecification:
    return UiSpecification(
        screen_name="Trip board",
        platform=platform,
        viewport_width=390 if platform == "mobile" else 1440,
        viewport_height=900,
        summary="Collaborative trip board",
        root=UiNode(
            id="root",
            kind="container",
            name="Root",
            children=[
                UiNode(
                    id="save",
                    kind="component",
                    name="Save",
                    requirement=ComponentRequirement(role="button"),
                )
            ],
        ),
    )


def test_requested_pages_have_screen_and_platform_names() -> None:
    assert page_name("Trip board", "desktop") == "Trip board · Desktop"
    assert page_name("Trip board", "mobile") == "Trip board · Mobile"


def test_component_count_is_scoped_per_screen() -> None:
    bindings = ComponentBindingSet(
        bindings=[
            ComponentBinding(node_id="save", status="resolved", component_id="button"),
            ComponentBinding(node_id="other", status="resolved", component_id="input"),
        ]
    )
    assert [item.node_id for item in binding_subset(bindings, specification()).bindings] == ["save"]


def test_component_instance_fills_its_declared_mount_frame() -> None:
    async def scenario() -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        async def call(_session: object, tool: str, arguments: dict[str, object]) -> dict[str, object]:
            calls.append((tool, arguments))
            if tool == "find_nodes":
                return {"nodes": [{"id": "slot", "x": 16, "y": 16, "width": 358, "height": 40}]}
            if tool == "create_instance":
                return {"id": "instance"}
            if tool == "get_node":
                return {"id": "slot", "width": 358, "height": 40}
            return {}

        gateway = SimpleNamespace(_call=call, _bind_text=AsyncMock())
        created = await OpenPencilGateway._insert_instances(
            gateway,
            object(),
            "doc",
            "page",
            ComponentBindingSet(
                bindings=[ComponentBinding(node_id="save", status="resolved", component_id="button")]
            ),
        )

        assert created == {"save": "instance"}
        resize = next(args for tool, args in calls if tool == "node_resize")
        assert resize["id"] == "instance"
        assert (resize["width"], resize["height"]) == (358, 40)

    asyncio.run(scenario())


def test_existing_workspace_preserves_pages_and_adds_its_own_token_page() -> None:
    async def scenario() -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        async def call(_session: object, tool: str, arguments: dict[str, object]) -> dict[str, object]:
            calls.append((tool, arguments))
            if tool == "open_file":
                return {"documentId": "doc-existing"}
            if tool == "list_pages":
                return {"pages": [{"id": "home", "name": "Home"}]}
            if tool == "create_page":
                return {"id": "tokens"}
            return {}

        gateway = SimpleNamespace(
            _call=call,
            _target=lambda value: (value.get("documentId", ""), ""),
        )
        result = await _prepare_project_document(
            gateway,
            object(),
            OpenPencilProfile(
                endpoint="http://127.0.0.1:7600/mcp",
                source_file="components.fig",
                output_file="workspace/Student portal.fig",
                target_mode="existing_file",
            ),
            [],
            {},
        )

        assert result == ("doc-existing", {}, "tokens", True, True, False)
        assert not any(tool == "rename_node" for tool, _ in calls)
        assert ("create_page", {"name": "Design Tokens", "document_id": "doc-existing"}) in calls

    asyncio.run(scenario())


def test_stale_checkpoint_discards_ids_without_replacing_document() -> None:
    async def scenario() -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        async def call(_session: object, tool: str, arguments: dict[str, object]) -> dict[str, object]:
            calls.append((tool, arguments))
            if tool == "open_file":
                return {"documentId": "stale-tab"}
            if tool == "create_page":
                return {"id": "tokens"}
            if tool == "list_pages":
                return {"pages": [{"id": "0:2", "name": "Page 1"}]}
            return {}

        gateway = SimpleNamespace(
            _call=call,
            _target=lambda value: (value.get("documentId", ""), ""),
        )
        result = await _prepare_project_document(
            gateway,
            object(),
            OpenPencilProfile(
                endpoint="http://127.0.0.1:7600/mcp",
                source_file="components.fig",
                output_file="generated/run/design.fig",
                target_mode="existing_file",
            ),
            [],
            {
                "palette_page_id": "0:5",
                "in_progress_page_id": "0:69",
                "in_progress_page_name": "Landing · Responsive",
                "local_components": {"source": "missing-node"},
            },
        )

        assert result == ("stale-tab", {}, "tokens", True, True, True)
        assert not any(tool in {"new_document", "delete_node"} for tool, _ in calls)

    asyncio.run(scenario())


def test_resume_reuses_live_page_and_skips_completed_screen() -> None:
    async def scenario() -> None:
        first = ScreenSpecification(
            screen_id="home",
            platforms=["desktop"],
            specification=specification("desktop").model_copy(update={"screen_name": "Home"}),
        )
        second = ScreenSpecification(
            screen_id="board",
            platforms=["mobile"],
            specification=specification("mobile"),
        )
        project = ProjectSpecification(
            brief=DesignBrief(
                product_name="Atlas",
                product_description="Travel planner",
                platforms=["desktop", "mobile"],
                screens=[ScreenBrief(name="Home"), ScreenBrief(name="Trip board")],
                output_filename="atlas.fig",
                scope_confirmed=True,
            ),
            design_context=ProjectDesignContext(
                product_summary="Travel planner",
                visual_direction="Cartographic",
            ),
            screens=[first, second],
        )
        calls: list[tuple[str, dict[str, object]]] = []

        @asynccontextmanager
        async def session(_endpoint: str):
            yield object()

        render_calls = 0

        async def call(_session: object, tool: str, arguments: dict[str, object]) -> dict[str, object]:
            nonlocal render_calls
            calls.append((tool, arguments))
            if tool == "list_documents":
                return {"documents": [{"id": "doc"}]}
            if tool == "get_page_tree":
                if arguments.get("page_id") == "components":
                    return {"children": [{"id": "local-button", "type": "COMPONENT"}]}
                return {"children": [{"id": "partial-root"}]}
            if tool == "get_jsx":
                return {"jsx": "<Frame />"}
            if tool == "list_pages":
                return {
                    "pages": [
                        {"id": "tokens", "name": "Design Tokens"},
                        {"id": "board-page", "name": "Trip board · Mobile"},
                        {"id": "home-page", "name": "Home · Desktop"},
                        {"id": "components", "name": "Components"},
                    ]
                }
            if tool == "create_page":
                return {"id": "board-page"}
            if tool == "render":
                render_calls += 1
                if render_calls == 1:
                    raise ExceptionGroup(
                        "MCP session failed",
                        [
                            AppError(
                                "OPENPENCIL_TOOL_FAILED",
                                "OpenPencil tool render failed",
                                "Unexpected token (107:17)",
                                502,
                                True,
                            )
                        ],
                    )
                return {"id": "board-root"}
            if tool == "delete_node":
                raise ExceptionGroup(
                    "MCP session failed",
                    [
                        AppError(
                            "OPENPENCIL_TOOL_FAILED",
                            "OpenPencil tool delete_node failed",
                            "{'error': 'Node \"stale-page\" not found'}",
                            502,
                            True,
                        )
                    ],
                )
            return {}

        gateway = SimpleNamespace(
            source=SimpleNamespace(pack=AsyncMock(return_value=[])),
            session=session,
            _call=call,
            _target=lambda value: (value.get("documentId", ""), ""),
            _insert_instances=AsyncMock(return_value=1),
            _capture_preview=AsyncMock(return_value=None),
        )
        checkpoint = {
            "document_id": "doc",
            "completed": ["home:desktop"],
            "palette_page_id": "tokens",
            "local_components": {"button": "local-button"},
            "screens": [
                {
                    "key": "home:desktop",
                    "screen_id": "home",
                    "screen_name": "Home",
                    "platform": "desktop",
                    "page_id": "home-page",
                    "page_name": "Home · Desktop",
                    "root_node_id": "home-root",
                    "expected_instances": 0,
                    "telemetry": {"instances": 0},
                }
            ],
            "last_screen": "board:mobile",
            "in_progress_page_id": "stale-page",
        }
        telemetry = {
            "instances": 1,
            "bounds": {"width": 390, "height": 900},
            "placeholders": 0,
            "overlaps": {},
            "root_node_id": "board-root",
            "small_touch_targets": [],
        }
        designer = AsyncMock(
            return_value={
                "root_id": "board-root",
                "telemetry": telemetry,
                "inspected": True,
                "trace": [{"tool": "render", "ok": True}],
            }
        )
        with patch("app.openpencil.project_executor.design_page", new=designer):
            result = await assemble_project(
                gateway,
                OpenPencilProfile(
                    endpoint="http://127.0.0.1:7600/mcp",
                    source_file="components.fig",
                    output_file="atlas.fig",
                ),
                project,
                ComponentBindingSet(
                    bindings=[
                        ComponentBinding(
                            node_id="save",
                            status="resolved",
                            component_id="button",
                        )
                    ]
                ),
                run_id=None,
                llm=AsyncMock(),
                prompts=SimpleNamespace(),
                checkpoint=checkpoint,
            )

        assert not any(tool == "open_file" for tool, _ in calls)
        assert not any(tool == "delete_node" for tool, _ in calls)
        assert designer.await_count == 1
        assert designer.await_args.kwargs["bindings"].bindings[0].component_id == "local-button"
        created_pages = [args for tool, args in calls if tool == "create_page"]
        assert created_pages == []
        assert designer.await_args.kwargs["root_id"] == "partial-root"
        assert all(args.get("page_id") == "tokens" for tool, args in calls if tool == "save_file")
        assert result["completed"] == ["board:mobile", "home:desktop"]
        assert len(result["screens"]) == 2
        assert result["screens"][-1]["expected_instances"] == 1
        assert result["screens"][-1]["telemetry"]["inspection_status"] == "reviewed"

    asyncio.run(scenario())
def test_old_responsive_spec_is_migrated_to_desktop_reference_canvas() -> None:
    old = specification("responsive").model_copy(update={"viewport_width": 390, "viewport_height": 844})
    migrated = specification_for_platform(old, "responsive")
    assert (migrated.viewport_width, migrated.viewport_height) == (1440, 1024)
