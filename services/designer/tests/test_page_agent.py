import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.errors import AppError
from app.core.prompts import PromptLibrary
from app.models import ComponentBinding, ComponentBindingSet, UiNode, UiSpecification
from app.openpencil.page_agent import design_page
from app.openpencil.qa import blocking_findings, component_styles


def spec() -> UiSpecification:
    return UiSpecification(
        screen_name="Orders",
        viewport_width=390,
        viewport_height=844,
        summary="Review orders",
        root=UiNode(id="root", name="Orders", kind="container"),
    )


def test_real_component_surface_underfill_is_visible_to_reflection() -> None:
    root = {
        "name": "root", "children": [{
            "id": "mount", "name": "component::login_button", "width": 342, "height": 40,
            "children": [{
                "id": "instance", "name": "Button", "type": "INSTANCE", "width": 342, "height": 40,
                "children": [{
                    "id": "paint", "name": "Button background", "type": "RECTANGLE", "width": 106,
                    "height": 40, "fills": [{"color": {"r": 0.1, "g": 0.8, "b": 0.8}}],
                }],
            }],
        }],
    }
    styles = component_styles(root)
    assert styles[0]["underfill"] is True
    assert styles[0]["surfaces"][0]["id"] == "paint"
    assert blocking_findings({"component_styles": styles}, 390)[0]["category"] == "component-underfill"


def test_repeated_invalid_canvas_edit_gets_one_fresh_context_then_stops() -> None:
    async def scenario() -> None:
        attempts = 0
        gateway = SimpleNamespace(
            _call=AsyncMock(return_value={"id": "root-1"}),
            _capture_preview=AsyncMock(return_value=None),
        )

        async def run_tools(**kwargs):
            nonlocal attempts
            attempts += 1
            tools = {tool.__name__: tool for tool in kwargs["tools"]}
            await tools["inspect_design_system"]()
            await tools["plan_design"]("One clear login action and a deliberate visual identity.")
            assert (await tools["render_page"]('<Frame name="Orders" />')).get("ok", True)
            bad = [{"tool": "", "arguments": {}}]
            for _ in range(3):
                result = await tools["edit_canvas"](bad)
                assert result["ok"] is False

        with pytest.raises(AppError, match="AGENT_STALLED"):
            await design_page(
                gateway, object(), llm=SimpleNamespace(run_tools=run_tools), prompts=PromptLibrary(),
                document_id="doc", page_id="page", specification=spec(),
                bindings=ComponentBindingSet(bindings=[]), component_context={},
            )
        assert gateway._call.await_count == 1
        assert attempts == 2

    asyncio.run(scenario())


def test_agent_receives_errors_and_repairs_same_page_then_reinspects() -> None:
    async def scenario() -> None:
        calls = []
        renders = 0

        async def call(session, tool, args):
            nonlocal renders
            calls.append((tool, args))
            if tool == "fetch_icons":
                return {"not_found": [name for name in args["names"] if name == "lucide:invalid"]}
            if tool == "search_icons":
                return {"invalid": {"icons": ["lucide:search"]}}
            if tool == "render":
                renders += 1
                if "BROKEN" in args["jsx"]:
                    raise ExceptionGroup(
                        "MCP error", [AppError("OPENPENCIL_TOOL_FAILED", "Render", "Unexpected token at line 2", 502)]
                    )
                return {"id": f"root-{renders}"}
            return {"jsx": '<Frame name="Live" />'}

        gateway = SimpleNamespace(
            _call=call,
            _insert_instances=AsyncMock(return_value={"save": "instance-save"}),
            _capture_preview=AsyncMock(return_value=(b"image", "png")),
        )
        jsx = '<Frame name="Orders"><Frame name="slot::save" /><Icon name="lucide:search" /></Frame>'

        async def run_tools(*, prompt, tools, before_model_callback, **_kwargs):
            by_name = {tool.__name__: tool for tool in tools}
            assert "Approved creative skeleton" in prompt
            assert "Design craft" in prompt
            assert (await by_name["render_page"](jsx))["ok"] is False
            await by_name["inspect_design_system"]()
            await by_name["plan_design"](
                "Editorial schedule with a strong day marker, warm violet accent, and visible completion checks."
            )
            assert "Fetch" in (await by_name["render_page"](jsx))["error"]
            missing = await by_name["fetch_icons"](["lucide:invalid"])
            assert missing["alternatives"]
            await by_name["fetch_icons"](["lucide:search"])
            assert "Unexpected token" in (await by_name["render_page"](jsx + "BROKEN"))["error"]
            assert (await by_name["render_page"](jsx))["instances"] == 1
            await by_name["inspect_page"]()
            reflected = await by_name["reflect_page"](
                "The form visibly exceeds its content frame.",
                ["Form exceeds content width"],
                True,
            )
            assert reflected["needs_refinement"] is True
            assert "finish_page" not in by_name
            model_request = SimpleNamespace(contents=[])
            await before_model_callback(None, model_request)
            assert model_request.contents[0].parts[1].inline_data.data == b"image"
            assert (await by_name["render_page"](jsx.replace("Orders", "Refined")))["ok"]
            premature = await by_name["reflect_page"]("Premature", [], False)
            assert premature["ok"] is False and "Inspect" in premature["error"]
            tree = await by_name["inspect_nodes"](["instance-save"])
            assert tree["nodes"]
            adjusted = await by_name["edit_canvas"](
                [
                    {
                        "tool": "update_node",
                        "arguments": {"id": "instance-save", "opacity": 0.96, "corner_radius": 18},
                    }
                ]
            )
            assert adjusted["operations"][0]["arguments"]["corner_radius"] == 18
            assert adjusted["observation"]["preview_attached"] is True
            blocked_reset = await by_name["render_page"](jsx.replace("Orders", "Rebuilt"))
            assert blocked_reset["ok"] is False and "discard" in blocked_reset["error"]
            unchanged = await by_name["render_page"](jsx.replace("Orders", "Refined"))
            assert unchanged["unchanged"] is True
            tool_context = SimpleNamespace(actions=SimpleNamespace(skip_summarization=False))
            reflected = await by_name["reflect_page"](
                "The refined layout fits the viewport and the required component remains mounted.",
                [],
                False,
                tool_context,
            )
            assert reflected["needs_refinement"] is False
            assert tool_context.actions.skip_summarization is True
            return "Done"

        blocking = {
            "placeholders": 0,
            "overlaps": {
                "overlaps": [
                    {
                        "category": "parent-overflow",
                        "severity": "critical",
                        "message": "Form exceeds content width",
                        "nodeA": {"name": "Form", "type": "FRAME"},
                        "nodeB": {"name": "Content", "type": "FRAME"},
                    }
                ]
            },
        }
        with (
            patch("app.openpencil.page_agent.measure_screen", AsyncMock(side_effect=[blocking, {}])),
            patch(
                "app.openpencil.page_agent.apply_unsplash_media", AsyncMock(return_value={"applied": 0, "assets": []})
            ),
        ):
            result = await design_page(
                gateway,
                object(),
                llm=SimpleNamespace(run_tools=run_tools),
                prompts=PromptLibrary(),
                document_id="doc",
                page_id="page",
                specification=spec(),
                bindings=ComponentBindingSet(
                    bindings=[ComponentBinding(node_id="save", status="resolved", component_id="button")]
                ),
                component_context={"button": "Inspected real component"},
            )
        assert result["finished"] and result["root_id"] == "root-3"
        assert gateway._insert_instances.await_count == 2
        render_calls = [args for tool, args in calls if tool == "render"]
        assert render_calls[-1]["replace_id"] == "root-2"
        assert all(args["document_id"] == "doc" and args["page_id"] == "page" for args in render_calls)
        component_updates = [args for tool, args in calls if tool == "update_node"]
        assert component_updates[-1]["id"] == "instance-save"
        assert component_updates[-1]["corner_radius"] == 18
        inspections = [record for record in result["trace"] if record["tool"] == "inspect"]
        reflections = [record for record in result["trace"] if record["tool"] == "reflect"]
        assert inspections[-1]["preview_attached"] is True
        assert inspections[-1]["live_jsx_chars"] > 0
        assert reflections[-1]["needs_refinement"] is False
        assert any(not record["ok"] for record in result["trace"])

    asyncio.run(scenario())


def test_missing_component_cannot_be_silently_replaced_with_a_drawing() -> None:
    async def scenario() -> None:
        gateway = SimpleNamespace(_call=AsyncMock())

        async def run_tools(**kwargs):
            tools = {tool.__name__: tool for tool in kwargs["tools"]}
            await tools["inspect_design_system"]()
            await tools["plan_design"]("Compact order form with an expressive action area and clear validation.")
            response = await tools["render_page"]('<Frame name="Fake button" />')
            assert "slot::save" in response["error"]

        with pytest.raises(AppError, match="DESIGN_INCOMPLETE"):
            await design_page(
                gateway,
                object(),
                llm=SimpleNamespace(run_tools=run_tools),
                prompts=PromptLibrary(),
                document_id="doc",
                page_id="page",
                specification=spec(),
                bindings=ComponentBindingSet(
                    bindings=[ComponentBinding(node_id="save", status="resolved", component_id="button")]
                ),
                component_context={},
            )
        gateway._call.assert_not_awaited()

    asyncio.run(scenario())


def test_missing_visual_preview_stops_the_agent_with_a_retryable_error() -> None:
    async def scenario() -> None:
        gateway = SimpleNamespace(
            _call=AsyncMock(side_effect=[{"id": "root-1"}, {"jsx": '<Frame name="Orders" />'}]),
            _capture_preview=AsyncMock(return_value=None),
        )

        async def run_tools(**kwargs):
            tools = {tool.__name__: tool for tool in kwargs["tools"]}
            await tools["inspect_design_system"]()
            await tools["plan_design"]("Quiet order review with high-contrast hierarchy and a decisive action.")
            assert (await tools["render_page"]('<Frame name="Orders" />'))["ok"]
            await tools["inspect_page"]()
            context = SimpleNamespace(actions=SimpleNamespace(skip_summarization=False))
            result = await tools["reflect_page"]("Looks complete", [], False, context)
            assert result["ok"] is False
            assert context.actions.skip_summarization is True

        with (
            patch("app.openpencil.page_agent.measure_screen", AsyncMock(return_value={})),
            patch(
                "app.openpencil.page_agent.apply_unsplash_media", AsyncMock(return_value={"applied": 0, "assets": []})
            ),
            pytest.raises(AppError, match="OPENPENCIL_PREVIEW_UNAVAILABLE"),
        ):
            await design_page(
                gateway,
                object(),
                llm=SimpleNamespace(run_tools=run_tools),
                prompts=PromptLibrary(),
                document_id="doc",
                page_id="page",
                specification=spec(),
                bindings=ComponentBindingSet(bindings=[]),
                component_context={},
            )

    asyncio.run(scenario())


def test_partial_insertion_failure_replaces_known_root_on_retry() -> None:
    async def scenario() -> None:
        gateway = SimpleNamespace(
            _call=AsyncMock(return_value={"id": "partial-root"}),
            _insert_instances=AsyncMock(side_effect=ValueError("Unknown text slot")),
        )

        async def run_tools(**kwargs):
            tools = {tool.__name__: tool for tool in kwargs["tools"]}
            await tools["inspect_design_system"]()
            await tools["plan_design"]("Focused order flow with a clear primary action.")
            for _ in range(2):
                result = await tools["render_page"]('<Frame><Frame name="slot::save" /></Frame>')
                assert "Unknown text slot" in result["error"]

        with pytest.raises(AppError, match="DESIGN_INCOMPLETE"):
            await design_page(
                gateway,
                object(),
                llm=SimpleNamespace(run_tools=run_tools),
                prompts=PromptLibrary(),
                document_id="doc",
                page_id="page",
                specification=spec(),
                bindings=ComponentBindingSet(
                    bindings=[ComponentBinding(node_id="save", status="resolved", component_id="button")]
                ),
                component_context={},
            )
        assert gateway._call.await_args_list[-1].args[2]["replace_id"] == "partial-root"

    asyncio.run(scenario())


def test_cancellation_is_not_converted_to_a_tool_error() -> None:
    async def scenario() -> None:
        gateway = SimpleNamespace(_call=AsyncMock(side_effect=asyncio.CancelledError()))

        async def run_tools(**kwargs):
            tools = {tool.__name__: tool for tool in kwargs["tools"]}
            await tools["fetch_icons"](["lucide:search"])

        with pytest.raises(asyncio.CancelledError):
            await design_page(
                gateway,
                object(),
                llm=SimpleNamespace(run_tools=run_tools),
                prompts=PromptLibrary(),
                document_id="doc",
                page_id="page",
                specification=spec(),
                bindings=ComponentBindingSet(bindings=[]),
                component_context={},
            )

    asyncio.run(scenario())


def test_agent_can_import_inspected_alternative_and_repair_binding() -> None:
    async def scenario():
        calls = []

        async def call(_, tool, args):
            calls.append((tool, args))
            if tool == "list_pages":
                return {"pages": [{"id": "library", "name": "Components"}]}
            if tool == "render":
                return {"id": "local-button" if "Button" in args["jsx"] else "local-icon"}
            return {}

        gateway = SimpleNamespace(
            _call=call,
            source=SimpleNamespace(
                pack=AsyncMock(
                    return_value=[
                        ("icon", '<Component name="Icon" />'),
                        ("button", '<Component name="Button"><Instance componentId="icon" /></Component>'),
                    ]
                )
            ),
        )
        bindings = ComponentBindingSet(bindings=[ComponentBinding(node_id="save", status="unresolved")])

        async def run_tools(**kwargs):
            tools = {tool.__name__: tool for tool in kwargs["tools"]}
            await tools["inspect_design_system"]()
            rejected = await tools["bind_component"]("save", "invented", "{}")
            assert not rejected["ok"]
            result = await tools["bind_component"]("save", "button", '{"Label":"Lưu"}')
            assert result["binding"]["component_id"] == "local-button"
            assert not (await tools["reflect_page"]("Not rendered", [], False))["ok"]

        with pytest.raises(AppError, match="DESIGN_INCOMPLETE"):
            await design_page(
                gateway,
                object(),
                llm=SimpleNamespace(run_tools=run_tools),
                prompts=PromptLibrary(),
                document_id="doc",
                page_id="page",
                specification=spec(),
                bindings=bindings,
                component_context={"candidates": [{"component_id": "button"}]},
                source_file="source.fig",
            )
        imports = [args for tool, args in calls if tool == "render"]
        assert len(imports) == 2 and all(args["page_id"] == "library" for args in imports)
        assert 'componentId="local-icon"' in imports[1]["jsx"]
        assert bindings.bindings[0].text_values == {"Label": "Lưu"}

    asyncio.run(scenario())
