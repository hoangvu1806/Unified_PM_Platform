import asyncio
from pathlib import Path

from app.models import DesignBrief, RunCreate, RunStage, RunStatus, ScreenBrief, ScreenWrite
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
        await store.set_run_data(run.id, run.revision, "sample", {"value": 1})

        assert await store.delete_session(session.id) is True
        assert await store.get_session(session.id) is None
        assert await store.get_run(run.id) is None
        assert await store.list_events(run.id) == []
        assert await store.list_run_data(run.id, run.revision) == {}
        assert await store.delete_session(session.id) is False

    asyncio.run(scenario())


def test_latest_session_run_data_survives_clarification_runs(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = make_test_store()
        await store.initialize()
        session = await store.create_session("Splash")
        upload_run = await store.create_run(
            session.id,
            RunCreate(prompt="Use my image", screen_name="Splash"),
        )
        assets = [{"id": "asset-123", "name": "Untitled.png", "usage": "exact"}]
        await store.set_run_data(upload_run.id, upload_run.revision, "exact_assets", assets)
        await store.create_run(
            session.id,
            RunCreate(prompt="mobile nhé", screen_name="Splash"),
        )

        assert await store.get_latest_session_run_data(session.id, "exact_assets") == assets

    asyncio.run(scenario())


def test_screens_keep_every_version(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = make_test_store()
        await store.initialize()
        session = await store.create_session("Kho")
        first = await store.save_screen(
            session.id, "danh-sach", ScreenWrite(name="Danh sách", platform="desktop", html="<main>v1</main>")
        )
        assert (first.version, first.width, first.position) == (1, 1440, 0)
        second = await store.save_screen(
            session.id, "danh-sach", ScreenWrite(name="Danh sách", html="<main>v2</main>", note="sửa"), updated_by="pm.hoa"
        )
        assert second.version == 2 and second.html == "<main>v2</main>" and second.updated_by == "pm.hoa"
        mobile = await store.save_screen(
            session.id, "tao-moi", ScreenWrite(name="Tạo mới", platform="mobile", html="<form></form>")
        )
        assert (mobile.width, mobile.position) == (390, 1)

        listed = await store.list_screens(session.id)
        assert [s.id for s in listed] == ["danh-sach", "tao-moi"] and listed[0].html is None
        old = await store.get_screen(session.id, "danh-sach", version=1)
        assert old and old.html == "<main>v1</main>" and old.version == 1
        assert [v.version for v in await store.list_screen_versions(session.id, "danh-sach")] == [2, 1]

        assert await store.delete_screen(session.id, "tao-moi") is True
        assert await store.get_screen(session.id, "tao-moi") is None
        await store.delete_session(session.id)
        assert await store.list_screens(session.id) == []

    asyncio.run(scenario())


def _files(prefix: str) -> list[str]:
    from platform_core.storage import get_storage

    return sorted(get_storage().keys(prefix))


def test_screen_html_lives_in_storage_per_project_and_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = make_test_store()
        await store.initialize()
        session = await store.create_session("Kho", project_id="PRJ-1")
        await store.save_screen(session.id, "home", ScreenWrite(name="Home", html="<main>v1</main>"))
        await store.save_screen(session.id, "home", ScreenWrite(name="Home", html="<main>v2</main>"))
        await store.save_screen(session.id, "cart", ScreenWrite(name="Cart", html="<main>cart</main>"))

        base = f"projects/PRJ-1/designer/sessions/{session.id}/screens/"
        assert _files(base) == [base + "cart/v0001.html", base + "home/v0001.html", base + "home/v0002.html"]
        listed = await store.list_screens(session.id, with_html=True)
        assert [s.html for s in listed] == ["<main>v2</main>", "<main>cart</main>"]

        assert await store.delete_screen(session.id, "cart") is True
        assert _files(base) == [base + "home/v0001.html", base + "home/v0002.html"]
        assert await store.delete_session(session.id) is True
        assert _files(f"projects/PRJ-1/designer/sessions/{session.id}/") == []

    asyncio.run(scenario())


def test_inline_html_from_older_versions_moves_to_storage(tmp_path: Path) -> None:
    async def scenario() -> None:
        from psycopg import connect

        from app.storage.store import Store
        from tests.pg import pg_test_dsn

        store = make_test_store()
        await store.initialize()
        session = await store.create_session("Cũ", project_id="PRJ-OLD")
        sid = str(session.id)
        with connect(pg_test_dsn(), autocommit=True) as db:  # the layout before HTML moved to storage
            db.execute(f'SET search_path TO "{store.schema}"')
            db.execute("ALTER TABLE screens ADD COLUMN html TEXT")
            db.execute("ALTER TABLE screen_versions ADD COLUMN html TEXT")
            for version, html in ((1, "<main>a</main>"), (2, "<main>b</main>")):
                db.execute(
                    "INSERT INTO screen_versions (session_id, screen_id, version, html, created_at) "
                    "VALUES (%s, 'home', %s, %s, '2026-01-01T00:00:00+00:00')", (sid, version, html))
            db.execute(
                "INSERT INTO screens (session_id, screen_id, name, platform, width, position, version, html, "
                "created_at, updated_at) VALUES (%s, 'home', 'Home', 'desktop', 1440, 0, 2, '<main>b</main>', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
                (sid,))

        upgraded = Store(store.dsn, schema=store.schema, max_size=2)
        await upgraded.initialize()

        assert len(_files(f"projects/PRJ-OLD/designer/sessions/{sid}/screens/home/")) == 2
        current = await upgraded.get_screen(session.id, "home")
        assert current and current.html == "<main>b</main>" and current.version == 2
        old = await upgraded.get_screen(session.id, "home", version=1)
        assert old and old.html == "<main>a</main>"
        with connect(pg_test_dsn(), autocommit=True) as db:
            columns = db.execute(
                "SELECT table_name FROM information_schema.columns WHERE table_schema=%s AND column_name='html' "
                "AND table_name IN ('screens', 'screen_versions')", (store.schema,)).fetchall()
        assert columns == []

    asyncio.run(scenario())


def test_uploaded_assets_are_scoped_to_the_project(tmp_path: Path) -> None:
    from platform_core.storage import get_storage

    from app.storage.assets import read_asset, save_asset

    assert save_asset("PRJ-1", "logo-png-abc", b"png") == "projects/PRJ-1/designer/assets/logo-png-abc"
    assert read_asset("PRJ-1", "logo-png-abc") == b"png"
    assert read_asset("PRJ-2", "logo-png-abc") is None
    get_storage().put("shared/designer/assets/old-png-1", b"legacy")  # uploaded before per-project assets
    assert read_asset("PRJ-1", "old-png-1") == b"legacy"
