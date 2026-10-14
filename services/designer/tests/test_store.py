import asyncio
from pathlib import Path

from app.models import (
    DesignBrief,
    OpenPencilProfile,
    RunCreate,
    RunStage,
    RunStatus,
    ScreenBrief,
    SessionWorkspace,
    WorkspaceActionDecision,
    WorkspaceActionTarget,
    WorkspaceScreenReference,
)
from tests.pg import make_test_store


def test_session_and_run_round_trip(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = make_test_store()
        await store.initialize()
        session = await store.create_session("Landing page")
        brief = DesignBrief(
            product_name="Atlas",
            product_description="A travel app",
            platforms=["mobile"],
            screens=[ScreenBrief(name="Home")],
            output_filename="atlas.fig",
            scope_confirmed=True,
        )
        await store.save_design_brief(session.id, brief)
        restored_session = await store.get_session(session.id)
        assert restored_session and restored_session.design_brief == brief
        run = await store.create_run(
            session.id,
            RunCreate(
                prompt="Create a calm commerce landing page",
                screen_name="Home",
                mcp_profile={
                    "endpoint": "http://127.0.0.1:7600/mcp",
                    "source_file": "system.fig",
                    "output_file": "generated/home.fig",
                },
            ),
        )

        restored = await store.get_run(run.id)

        assert restored is not None
        assert restored.screen_name == "Home"
        assert restored.library_ids == []
        assert restored.mcp_profile is not None
        assert restored.mcp_profile.output_file == f"generated/{run.id}/Home.fig"
        updated = await store.update_mcp_profile(
            run.id,
            OpenPencilProfile(
                endpoint="http://127.0.0.1:7600/mcp",
                source_file="new-system.fig",
                output_file="generated/retry.fig",
            ),
        )
        assert updated.mcp_profile
        assert updated.mcp_profile.source_file == "new-system.fig"
        assert updated.mcp_profile.output_file == f"generated/{run.id}/atlas.fig"
        await store.update_run(
            run.id,
            stage=RunStage.FINISHED,
            status=RunStatus.COMPLETED,
            intent="chat",
            assistant_message="Xin chào!",
        )
        answered = await store.get_run(run.id)
        assert answered and answered.intent == "chat"
        assert answered.assistant_message == "Xin chào!"

        duplicate = await store.create_run(
            session.id,
            RunCreate(
                prompt="Create another calm commerce landing page",
                screen_name="Home.fig",
                mcp_profile={
                    "endpoint": "http://127.0.0.1:7600/mcp",
                    "source_file": "system.fig",
                },
            ),
        )
        assert duplicate.mcp_profile
        assert duplicate.mcp_profile.output_file == f"generated/{duplicate.id}/Home.fig"
        assert duplicate.mcp_profile.output_file != restored.mcp_profile.output_file

    asyncio.run(scenario())


def test_session_workspace_is_persisted_and_reused_by_later_runs(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        store = make_test_store()
        await store.initialize()
        session = await store.create_session("Student portal")
        workspace = SessionWorkspace(
            document_id="doc-42",
            document_path="generated/first/Student portal.fig",
            document_name="Student portal",
            page_id="page-home",
            page_name="Home · Mobile",
        )
        updated = await store.update_session_workspace(session.id, workspace)

        assert updated.workspace == workspace
        run = await store.create_run(
            session.id,
            RunCreate(
                prompt="Refine the login page spacing",
                screen_name="Login",
                mcp_profile={
                    "endpoint": "http://127.0.0.1:7600/mcp",
                    "source_file": "system.fig",
                },
            ),
        )

        assert run.mcp_profile is not None
        assert run.mcp_profile.target_mode == "existing_file"
        assert run.mcp_profile.output_file == workspace.document_path
        restored = await store.get_session(session.id)
        assert restored and restored.workspace == workspace

    asyncio.run(scenario())


def test_pending_workspace_action_round_trip(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = make_test_store()
        await store.initialize()
        session = await store.create_session("Aurora")
        pending = WorkspaceActionDecision(
            action="clarify",
            reply="Create both pages?",
            requires_confirmation=True,
            targets=[
                WorkspaceActionTarget(
                    action="add_page",
                    screen_id="UIT-04",
                    new_page_name="Place Inventory Hold · Mobile",
                    instruction="Create the inventory hold screen",
                )
            ],
        )

        await store.set_pending_workspace_action(session.id, pending)
        restored = await store.get_session(session.id)
        assert restored and restored.pending_workspace_action == pending

        await store.set_pending_workspace_action(session.id, None)
        cleared = await store.get_session(session.id)
        assert cleared and cleared.pending_workspace_action is None

    asyncio.run(scenario())


def test_workspace_screen_registry_uses_stable_screen_and_page_ids(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        store = make_test_store()
        await store.initialize()
        session = await store.create_session("Aurora")
        reference = WorkspaceScreenReference(
            screen_id="UIT-07",
            page_id="0:700",
            page_name="Aurora - Production investigation track · Mobile",
            platform="mobile",
        )

        await store.update_session_screen_registry(
            session.id, {reference.screen_id: reference}
        )
        restored = await store.get_session(session.id)

        assert restored
        assert restored.screen_registry["UIT-07"] == reference

    asyncio.run(scenario())


def test_delete_session_cascades_to_all_run_data(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = make_test_store()
        await store.initialize()
        session = await store.create_session("Disposable conversation")
        run = await store.create_run(
            session.id,
            RunCreate(prompt="Draft a screen", screen_name="Home"),
        )
        await store.add_event(run.id, run.revision, "run.created", {"ok": True})
        await store.add_review(run.id, run.revision, "specification", "approved", "")
        await store.set_artifact(run.id, run.revision, "sample", {"value": 1})

        assert await store.delete_session(session.id) is True
        assert await store.get_session(session.id) is None
        assert await store.get_run(run.id) is None
        assert await store.list_events(run.id) == []
        assert await store.list_artifacts(run.id, run.revision) == {}
        assert await store.delete_session(session.id) is False

    asyncio.run(scenario())


def test_latest_session_artifact_survives_clarification_runs(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = make_test_store()
        await store.initialize()
        session = await store.create_session("Splash")
        upload_run = await store.create_run(
            session.id,
            RunCreate(prompt="Use my image", screen_name="Splash"),
        )
        assets = [{"id": "asset-123", "name": "Untitled.png", "usage": "exact"}]
        await store.set_artifact(upload_run.id, upload_run.revision, "exact_assets", assets)
        await store.create_run(
            session.id,
            RunCreate(prompt="mobile nhé", screen_name="Splash"),
        )

        assert await store.get_latest_session_artifact(session.id, "exact_assets") == assets

    asyncio.run(scenario())
