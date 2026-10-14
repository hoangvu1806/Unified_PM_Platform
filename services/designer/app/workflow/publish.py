"""Publish finished designs to the project's Assets (Sprint 4).

When a run completes with an OpenPencil output file, the .fig is read from the
designer's OpenPencil instance, copied to platform storage and registered as a
``designer_output`` artifact (version = run revision). Designs started from a
BA handoff link to the BA package version they were made from, so a newer BA
version marks them stale. Failures are logged; they never affect the run.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from ..models import RunStatus

if TYPE_CHECKING:
    from .service import RunService

logger = logging.getLogger("designer_agent.publish")


async def publish_design(service: "RunService", run_id: UUID) -> None:
    try:
        run = await service.store.get_run(run_id)
        if run is None or run.status != RunStatus.COMPLETED or not run.mcp_profile:
            return
        artifact = await service.store.get_artifact(run.id, run.revision, "openpencil_artifact") or {}
        path = str(artifact.get("output_file") or "")
        if not path:
            return  # chat-only turn, nothing was drawn
        session = await service.store.get_session(run.session_id)
        if session is None or not session.project_id:
            return

        from platform_core import artifacts
        from platform_core.storage import get_storage, project_key

        existing = artifacts.latest("designer_output", str(run.id))
        if existing and existing["version"] >= run.revision:
            return
        raw, media_type = await service.openpencil.download_workspace_file(run.mcp_profile.endpoint, path)
        filename = path.replace("\\", "/").rsplit("/", 1)[-1] or "design.fig"
        key = project_key(session.project_id, "designer", "outputs", str(run.id), f"r{run.revision}-{filename}")
        get_storage().put(key, raw, content_type=media_type or "application/octet-stream")
        row, created = artifacts.register(
            project_id=session.project_id,
            kind="designer_output",
            source_module="designer",
            source_ref=str(run.id),
            version=run.revision,
            title=f"{session.title} — {run.screen_name}",
            storage_key=key,
            derived_from_id=session.source_artifact_id,
            meta={"session_id": str(session.id), "file": filename, "output_file": path},
            created_by=session.created_by,
        )
        if created:
            logger.info("Published design %s r%s -> %s", run.id, run.revision, key)
    except Exception:  # noqa: BLE001
        logger.exception("Publishing design for run %s failed", run_id)
