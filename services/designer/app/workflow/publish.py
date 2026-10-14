"""Publish designs to the project's Assets.

As soon as a run has drawn its screens and waits for the final review, the
OpenPencil output file (.fig) is copied to platform storage and registered as a
``designer_output`` artifact (version = run revision) with ``meta.state =
"review"``. When the final review is approved (run completed) the same version
is refreshed with the latest file and ``meta.state = "approved"``. Designs
started from a BA handoff link to the BA package version they were made from,
so a newer BA version marks them stale. Failures are logged; they never affect
the run.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from ..models import RunStage, RunStatus

if TYPE_CHECKING:
    from .service import RunService

logger = logging.getLogger("designer_agent.publish")


def _state(run) -> str | None:
    if run.status == RunStatus.COMPLETED:
        return "approved"
    if run.status == RunStatus.WAITING_REVIEW and run.stage == RunStage.REVIEW_FINAL:
        return "review"
    return None


def _publish_spec(session, run, state: str) -> None:
    """The approved UI specification next to the design file (same revision, same BA link)."""
    from platform_core import artifacts
    from platform_core.storage import get_storage, project_key

    spec = run.specification
    if spec is None:
        return
    try:
        body = json.dumps(
            spec.model_dump(mode="json") if hasattr(spec, "model_dump") else spec,
            ensure_ascii=False, indent=2,
        ).encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        key = project_key(session.project_id, "designer", "outputs", str(run.id), f"r{run.revision}-ui-spec.json")
        meta = {"session_id": str(session.id), "state": state}
        existing = artifacts.latest("ui_spec", str(run.id))
        if existing and existing["version"] == run.revision:
            if existing.get("content_hash") != digest or (existing.get("meta") or {}).get("state") != state:
                get_storage().put(key, body, content_type="application/json")
                artifacts.update(existing["id"], storage_key=key, content_hash=digest, meta=meta)
            return
        if existing and existing["version"] > run.revision:
            return
        get_storage().put(key, body, content_type="application/json")
        artifacts.register(
            project_id=session.project_id,
            kind="ui_spec",
            source_module="designer",
            source_ref=str(run.id),
            version=run.revision,
            title=f"{session.title} — UI spec",
            storage_key=key,
            content_hash=digest,
            derived_from_id=session.source_artifact_id,
            meta=meta,
            created_by=session.created_by,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Publishing UI spec for run %s failed", run.id)


async def publish_design(service: "RunService", run_id: UUID) -> None:
    try:
        run = await service.store.get_run(run_id)
        state = _state(run) if run is not None else None
        if state is None or not run.mcp_profile:
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
        if existing and existing["version"] > run.revision:
            return
        raw, media_type = await service.openpencil.download_workspace_file(run.mcp_profile.endpoint, path)
        digest = hashlib.sha256(raw).hexdigest()
        filename = path.replace("\\", "/").rsplit("/", 1)[-1] or "design.fig"
        key = project_key(session.project_id, "designer", "outputs", str(run.id), f"r{run.revision}-{filename}")
        meta = {"session_id": str(session.id), "file": filename, "output_file": path, "state": state}

        _publish_spec(session, run, state)

        if existing and existing["version"] == run.revision:
            old_meta = existing.get("meta") or {}
            if existing.get("content_hash") == digest and old_meta.get("state") == state:
                return
            get_storage().put(key, raw, content_type=media_type or "application/octet-stream")
            artifacts.update(existing["id"], storage_key=key, content_hash=digest, meta=meta)
            logger.info("Design %s r%s updated (%s) -> %s", run.id, run.revision, state, key)
            return

        get_storage().put(key, raw, content_type=media_type or "application/octet-stream")
        _row, created = artifacts.register(
            project_id=session.project_id,
            kind="designer_output",
            source_module="designer",
            source_ref=str(run.id),
            version=run.revision,
            title=f"{session.title} — {run.screen_name}",
            storage_key=key,
            content_hash=digest,
            derived_from_id=session.source_artifact_id,
            meta=meta,
            created_by=session.created_by,
        )
        if created:
            logger.info("Published design %s r%s (%s) -> %s", run.id, run.revision, state, key)
    except Exception:  # noqa: BLE001
        logger.exception("Publishing design for run %s failed", run_id)
