"""designer-api: save a screen in SESSION_ID, finish a run and publish the design bundle."""
import asyncio, json, os, sys
from uuid import UUID

sys.path.insert(0, "/app")
from app.core.config import get_settings  # noqa: E402
from app.models import RunCreate, RunStage, RunStatus, ScreenWrite  # noqa: E402
from app.render import Renderer  # noqa: E402
from app.storage.store import Store  # noqa: E402
from app.workflow.publish import publish_design  # noqa: E402

SCREEN = '<main class="p-8"><h1 class="text-2xl font-semibold">Yêu cầu vật tư</h1><button class="mt-4 rounded-lg bg-primary px-4 py-2 text-primary-foreground">Gửi</button></main>'


class Service:
    def __init__(self, store, renderer):
        self.store, self.renderer = store, renderer


async def main():
    store = Store(get_settings().postgres_dsn)
    await store.initialize()
    renderer = Renderer()
    session = UUID(os.environ["SESSION_ID"])
    await store.save_screen(session, "yeu-cau", ScreenWrite(name="Yêu cầu vật tư", platform="desktop", html=SCREEN))
    run = await store.create_run(session, RunCreate(prompt="e2e", screen_name="Yêu cầu vật tư"))
    spec = {"schema_version": "html-1", "screens": [{"id": "yeu-cau", "name": "Yêu cầu vật tư", "platform": "desktop"}]}
    await store.update_run(run.id, stage=RunStage.FINISHED, status=RunStatus.COMPLETED, intent="start_design",
                           specification=spec)
    await publish_design(Service(store, renderer), run.id)
    from platform_core import artifacts
    row = artifacts.latest("designer_output", str(run.id))
    assert row and row["derived_from_id"], "design must be registered and linked to the BA package"
    assert row["meta"]["state"] == "approved" and row["meta"]["format"] == "html"
    print(json.dumps({"design": row["id"], "derived_from": row["derived_from_id"], "key": row["storage_key"]}))
    await renderer.close()
    await store.close()

asyncio.run(main())
