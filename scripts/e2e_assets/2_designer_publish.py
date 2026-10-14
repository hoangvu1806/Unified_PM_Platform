"""designer-api: finish a run in SESSION_ID and publish it (OpenPencil download stubbed)."""
import asyncio, json, os, sys
from uuid import UUID

sys.path.insert(0, "/app")
from app.core.config import get_settings  # noqa: E402
from app.models import RunCreate, RunStatus, RunStage, OpenPencilProfile  # noqa: E402
from app.storage.store import Store  # noqa: E402
from app.workflow.publish import publish_design  # noqa: E402


class StubOpenPencil:
    async def download_workspace_file(self, endpoint, path):
        return b"FIG-E2E-BYTES", "application/octet-stream"


class Service:
    def __init__(self, store):
        self.store, self.openpencil = store, StubOpenPencil()


async def main():
    store = Store(get_settings().postgres_dsn)
    await store.initialize()
    session = UUID(os.environ["SESSION_ID"])
    profile = OpenPencilProfile(endpoint="http://openpencil:7600/mcp", source_file="lib.fig")
    run = await store.create_run(session, RunCreate(prompt="e2e", screen_name="Home", mcp_profile=profile))
    await store.set_artifact(run.id, run.revision, "openpencil_artifact", {"output_file": "generated/e2e/Home.fig"})
    await store.update_run(run.id, stage=RunStage.FINISHED, status=RunStatus.COMPLETED)
    await publish_design(Service(store), run.id)
    from platform_core import artifacts
    row = artifacts.latest("designer_output", str(run.id))
    assert row and row["derived_from_id"], "design must be registered and linked to the BA package"
    print(json.dumps({"design": row["id"], "derived_from": row["derived_from_id"], "key": row["storage_key"]}))
    await store.close()

asyncio.run(main())
