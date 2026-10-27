"""Publish designs to the project's Assets.

The UI specification of a run is registered as a ``ui_spec`` artifact (version =
run revision) as soon as it exists. Designs started from a BA handoff link to the
BA package version they were made from, so a newer BA version marks them stale.
The design bundle (``designer_output``: HTML, PNG, .fig) is published by the HTML
designer once it renders screens. Failures are logged; they never affect the run.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from ..models import RunStatus

if TYPE_CHECKING:
    from .service import RunService

logger = logging.getLogger("designer_agent.publish")


def _spec_state(run) -> str:
    if run.status == RunStatus.COMPLETED and run.intent != "design":
        return "approved"
    return "review" if run.status == RunStatus.WAITING_REVIEW else "draft"


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
        if run is None:
            return
        session = await service.store.get_session(run.session_id)
        if session is None or not session.project_id:
            return
        # The UI spec goes to Assets as soon as it exists — no approval needed first.
        if run.specification is not None:
            _publish_spec(session, run, _spec_state(run))
    except Exception:  # noqa: BLE001
        logger.exception("Publishing design for run %s failed", run_id)
