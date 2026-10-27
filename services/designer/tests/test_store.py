import asyncio
from pathlib import Path

from app.models import DesignBrief, RunCreate, RunStage, RunStatus, ScreenBrief
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
            scope_confirmed=True,
        )
        await store.save_design_brief(session.id, brief)
        restored_session = await store.get_session(session.id)
        assert restored_session and restored_session.design_brief == brief
        run = await store.create_run(
            session.id,
            # Clients of the OpenPencil designer may still send mcp_profile; it is ignored.
            RunCreate(prompt="Create a calm commerce landing page", screen_name="Home", mcp_profile={"endpoint": "x"}),
        )

        restored = await store.get_run(run.id)

        assert restored is not None
        assert restored.screen_name == "Home"
        assert restored.library_ids == []
        assert restored.specification is None
        spec = {"screens": [{"id": "home", "name": "Home"}]}
        await store.update_run(
            run.id,
            stage=RunStage.FINISHED,
            status=RunStatus.COMPLETED,
            specification=spec,
            intent="chat",
            assistant_message="Xin chào!",
        )
        answered = await store.get_run(run.id)
        assert answered and answered.intent == "chat"
        assert answered.assistant_message == "Xin chào!"
        assert answered.specification == spec

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
