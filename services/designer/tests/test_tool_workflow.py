import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from app.core.errors import AppError
from app.core.llm import AdkProvider
from app.core.prompts import PromptLibrary
from app.models import (
    ComponentBindingSet,
    ConversationDecision,
    OpenPencilProfile,
    PageSkeleton,
    SectionPlan,
    SessionWorkspace,
    UiNode,
    UiSpecification,
    WorkspaceActionDecision,
    WorkspaceActionTarget,
    WorkspacePagePlan,
    WorkspacePageSectionPlan,
)
from app.workflow.workspace_agent import handle_workspace_message


def test_native_adk_keeps_tool_errors_in_conversation() -> None:
    seen = []

    class ScriptedModel(BaseLlm):
        model: str = "scripted"

        async def generate_content_async(self, llm_request, stream=False):
            seen.append(llm_request)
            responses = [
                part.function_response
                for content in llm_request.contents
                for part in content.parts or []
                if part.function_response
            ]
            if not responses:
                part = types.Part.from_function_call(name="render", args={"jsx": "broken"})
            elif responses[-1].response.get("error"):
                assert "Syntax error at line 1" in responses[-1].response["error"]
                part = types.Part.from_function_call(name="render", args={"jsx": "fixed"})
            else:
                part = types.Part.from_text(text="Finished")
            yield LlmResponse(content=types.Content(role="model", parts=[part]))

    async def render(jsx: str) -> dict:
        """Render a test fragment and return errors for repair."""
        if jsx == "broken":
            raise ValueError("Syntax error at line 1")
        return {"ok": True}

    async def scenario():
        provider = AdkProvider(
            SimpleNamespace(api_key="test", base_url="test", cleaned_base_url="test", llm_model="test")
        )
        with patch("app.core.llm.LiteLlm", return_value=ScriptedModel()):
            assert (
                await provider.run_tools(
                    prompt="Repair JSX w={number}, bg={primaryColor} through tools.", tools=[render], max_turns=4
                )
                == "Finished"
            )
        assert len(seen) == 3

    asyncio.run(scenario())


def test_native_adk_continues_same_session_when_model_stops_before_completion_gate() -> None:
    complete = False
    seen = []

    class ScriptedModel(BaseLlm):
        model: str = "scripted"

        async def generate_content_async(self, llm_request, stream=False):
            seen.append(llm_request)
            responses = [
                part.function_response
                for content in llm_request.contents
                for part in content.parts or []
                if part.function_response
            ]
            user_turns = sum(content.role == "user" for content in llm_request.contents)
            if responses:
                part = types.Part.from_text(text="Finished through the completion gate")
            elif user_turns > 1:
                part = types.Part.from_function_call(name="finish", args={})
            else:
                part = types.Part.from_text(text="I will fix the remaining issues next.")
            yield LlmResponse(content=types.Content(role="model", parts=[part]))

    async def finish() -> dict:
        """Mark the scripted task complete."""
        nonlocal complete
        complete = True
        return {"ok": True}

    async def scenario():
        provider = AdkProvider(
            SimpleNamespace(api_key="test", base_url="test", cleaned_base_url="test", llm_model="test")
        )
        with patch("app.core.llm.LiteLlm", return_value=ScriptedModel()):
            result = await provider.run_tools(
                prompt="Finish with the tool.",
                tools=[finish],
                max_turns=4,
                stop_when=lambda: complete,
            )
        assert result == "Finished through the completion gate"
        assert complete and len(seen) == 3

    asyncio.run(scenario())


def test_native_adk_reports_semantic_stall_instead_of_waiting_forever() -> None:
    seen = []

    class ScriptedModel(BaseLlm):
        model: str = "scripted"

        async def generate_content_async(self, llm_request, stream=False):
            seen.append(llm_request)
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part.from_text(text="I will act next.")])
            )

    async def unused_tool() -> dict:
        """A tool the stalled model should have called."""
        return {"ok": True}

    async def scenario():
        provider = AdkProvider(
            SimpleNamespace(api_key="test", base_url="test", cleaned_base_url="test", llm_model="test")
        )
        with patch("app.core.llm.LiteLlm", return_value=ScriptedModel()):
            with pytest.raises(AppError) as caught:
                await provider.run_tools(
                    prompt="Use the tool.",
                    tools=[unused_tool],
                    stop_when=lambda: False,
                    progress_token=lambda: "unchanged-canvas",
                )
        assert caught.value.code == "AGENT_STALLED"
        assert len(seen) == 2

    asyncio.run(scenario())


def test_structured_retry_receives_previous_invalid_response_and_validation_error() -> None:
    async def scenario():
        provider = AdkProvider(SimpleNamespace())
        provider.run_tools = AsyncMock(side_effect=['{"intent":"wrong"}', '{"intent":"chat","reply":"Hello"}'])
        with patch("app.core.llm.asyncio.sleep", new=AsyncMock()):
            result = await provider.structured(prompt="Answer the greeting", schema=ConversationDecision)
        assert result.intent == "chat"
        retry = provider.run_tools.await_args_list[1].kwargs["message"].parts[0].text
        assert '{"intent":"wrong"}' in retry and "Validation error" in retry

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["edit", "new", "resume_empty", "multiple"])
def test_workspace_uses_skeleton_components_and_same_designer_in_order(mode: str) -> None:
    async def scenario():
        workspace = SessionWorkspace(
            document_id="doc",
            document_path="project.fig",
            document_name="Project",
            page_id="old-page",
            page_name="Orders",
        )
        run = SimpleNamespace(
            id=uuid4(),
            session_id=uuid4(),
            revision=1,
            prompt="Design order details",
            style_name="editorial",
            library_ids=[],
            mcp_profile=OpenPencilProfile(
                endpoint="http://127.0.0.1:7600/mcp",
                source_file="source.fig",
                output_file="project.fig",
                target_mode="existing_file",
            ),
        )
        pages = [{"id": "old-page", "name": "Orders"}]
        if mode == "resume_empty":
            pages.append({"id": "empty-page", "name": "Details"})
        roots = {"old-page": "old-root"}
        jsx_by_page = {"old-page": '<Frame name="Before" />'}
        calls = []
        order = []

        @asynccontextmanager
        async def session(_):
            yield object()

        async def call(_, tool, args):
            calls.append((tool, args))
            page = args.get("page_id", "old-page")
            if tool == "list_pages":
                return {"pages": list(pages)}
            if tool == "get_page_tree":
                return {"children": [{"id": roots[page], "name": "Canvas"}] if page in roots else []}
            if tool == "get_jsx":
                return {"jsx": jsx_by_page.get(page, "")}
            if tool == "create_page":
                new_page = {"id": f"page-{len(pages)}", "name": args["name"]}
                pages.append(new_page)
                return new_page
            return {}

        targets = (
            [WorkspaceActionTarget(action="edit_page", page_id="old-page", instruction="Edit spacing")]
            if mode == "edit"
            else [
                WorkspaceActionTarget(
                    action="add_page", new_page_name=name, screen_id=name.lower(), instruction=f"Design {name}"
                )
                for name in (["Details", "History"] if mode == "multiple" else ["Details"])
            ]
        )

        async def structured(*, schema, **kwargs):
            if schema == WorkspaceActionDecision:
                return WorkspaceActionDecision(action=targets[0].action, targets=targets)
            if schema == WorkspacePagePlan:
                return WorkspacePagePlan(
                    page_name="Details",
                    purpose="Review details",
                    sections=[WorkspacePageSectionPlan(id="detail", name="Details", purpose="Show details")],
                )
            if schema == PageSkeleton:
                order.append("skeleton")
                return PageSkeleton(
                    screen_name="Details",
                    viewport_width=390,
                    viewport_height=844,
                    summary="Details",
                    sections=[
                        SectionPlan(
                            id="detail",
                            role="content",
                            name="Details",
                            intent="Show the requested details clearly",
                        )
                    ],
                )
            if schema == UiSpecification:
                return UiSpecification(
                    screen_name="Details",
                    viewport_width=390,
                    viewport_height=844,
                    summary="Details",
                    root=UiNode(
                        id="root",
                        kind="container",
                        name="Details",
                        children=[UiNode(id="detail", kind="container", name="Details")],
                    ),
                )
            raise AssertionError(schema)

        async def prepare(*args):
            order.append("components")
            return ComponentBindingSet(bindings=[]), {}

        async def designer(*args, **kwargs):
            order.append("design")
            assert order[-3:] == ["skeleton", "components", "design"]
            if mode != "edit":
                assert kwargs["root_id"] == ""  # never replace the reference page
            page = kwargs["page_id"]
            roots[page] = f"root-{page}"
            jsx_by_page[page] = '<Frame name="After" />'
            await kwargs["on_event"]({"tool": "render", "ok": True})
            return {"root_id": roots[page], "jsx": jsx_by_page[page], "summary": "Updated", "trace": []}

        store = SimpleNamespace(
            get_session=AsyncMock(return_value=SimpleNamespace(workspace=workspace)),
            update_run=AsyncMock(),
            set_artifact=AsyncMock(),
            update_session_workspace=AsyncMock(),
        )
        owner = SimpleNamespace(
            store=store,
            events=SimpleNamespace(emit=AsyncMock()),
            prompts=PromptLibrary(),
            llm=SimpleNamespace(structured=structured),
            openpencil=SimpleNamespace(session=session, _call=call, _capture_preview=AsyncMock(return_value=None)),
        )
        with (
            patch("app.workflow.workspace_agent.prepare_workspace_components", side_effect=prepare),
            patch("app.workflow.workspace_agent.design_page", side_effect=designer) as design,
        ):
            assert await handle_workspace_message(owner, run, conversation_history="[]")
        expected = 2 if mode == "multiple" else 1
        assert design.await_count == expected
        creations = [args for tool, args in calls if tool == "create_page"]
        assert len(creations) == (0 if mode in {"edit", "resume_empty"} else expected)
        assert store.set_artifact.await_count >= expected

    asyncio.run(scenario())


def test_structured_output_does_not_silently_complete_truncated_json() -> None:
    from app.core.llm import parse_structured_output

    with pytest.raises(AppError, match="LLM_OUTPUT_INVALID"):
        parse_structured_output('{"intent":"chat","reply":"unfinished', ConversationDecision)
