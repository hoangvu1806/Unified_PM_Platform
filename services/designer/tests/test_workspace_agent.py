import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.models import (
    OpenPencilProfile,
    SessionWorkspace,
    WorkspaceActionDecision,
    WorkspaceActionTarget,
)
from app.workflow.workspace_agent import _exact_page_match, handle_workspace_message


def test_new_page_identity_never_fuzzy_matches_a_semantically_similar_page() -> None:
    pages = [
        {
            "id": "0:487",
            "name": "Aurora - Lab investigation track · Mobile",
        }
    ]

    assert _exact_page_match(pages, "Aurora - Production investigation track · Mobile") is None
    assert _exact_page_match(pages, "  AURORA - LAB INVESTIGATION TRACK · MOBILE  ") == pages[0]


def test_workspace_decision_normalizes_generic_design_alias_from_targets() -> None:
    decision = WorkspaceActionDecision.model_validate(
        {
            "action": "design",
            "targets": [
                {
                    "action": "add_page",
                    "screen_id": "UIT-09",
                    "new_page_name": "Escalate Critical · Mobile",
                }
            ],
        }
    )

    assert decision.action == "add_page"
    assert decision.targets[0].action == "add_page"


def test_workspace_target_normalizes_generic_design_alias_structurally() -> None:
    target = WorkspaceActionTarget.model_validate(
        {
            "action": "design",
            "screen_id": "UIT-09",
            "new_page_name": "Escalate Critical · Mobile",
        }
    )

    assert target.action == "add_page"


def test_workspace_chat_does_not_start_design_tools() -> None:
    async def scenario() -> None:
        workspace = SessionWorkspace(
            document_id="doc-1",
            document_path="generated/project.fig",
            document_name="Project",
            page_id="page-1",
            page_name="Page 1",
        )
        run = SimpleNamespace(
            id=uuid4(),
            session_id=uuid4(),
            revision=1,
            prompt="What page is open?",
            style_name="minimal",
            mcp_profile=OpenPencilProfile(
                endpoint="http://127.0.0.1:7600/mcp",
                source_file="components.fig",
                output_file=workspace.document_path,
                target_mode="existing_file",
            ),
        )

        @asynccontextmanager
        async def mcp_session(_endpoint: str):
            yield object()

        async def call(_session: object, tool: str, _arguments: dict[str, object]) -> dict[str, object]:
            if tool == "list_pages":
                return {"pages": [{"id": "page-1", "name": "Page 1"}]}
            if tool == "get_selection":
                return {"selection": []}
            return {}

        structured = AsyncMock(return_value=WorkspaceActionDecision(action="chat", reply="Page 1 is open."))
        store = SimpleNamespace(
            get_session=AsyncMock(
                return_value=SimpleNamespace(
                    workspace=workspace,
                    design_brief=None,
                    screen_registry={},
                    pending_workspace_action=None,
                )
            ),
            set_pending_workspace_action=AsyncMock(),
            update_run=AsyncMock(),
        )
        owner = SimpleNamespace(
            store=store,
            events=SimpleNamespace(emit=AsyncMock()),
            llm=SimpleNamespace(structured=structured),
            prompts=SimpleNamespace(render=lambda name, **_values: name),
            openpencil=SimpleNamespace(session=mcp_session, _call=call),
        )

        handled = await handle_workspace_message(owner, run, conversation_history="[]")

        assert handled is True
        assert structured.await_count == 1
        assert store.update_run.await_args.kwargs["intent"] == "chat"

    asyncio.run(scenario())
