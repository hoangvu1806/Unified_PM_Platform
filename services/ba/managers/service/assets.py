"""Publish exported BA packages to the project's Assets (Sprint 4).

Each export stores the Common Envelope in platform storage and registers a
``ba_package`` artifact. The version only moves when the package content
(``payload``) changes, so re-exporting an unchanged feature is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from managers.database.connection import SessionLocal
from managers.database.models import BaPackageModel

logger = logging.getLogger(__name__)


def _content_hash(envelope: dict[str, Any]) -> str:
    body = envelope.get("payload", envelope)
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def publish_ba_package(session_id: str, envelope: dict[str, Any], created_by: str | None) -> dict[str, Any] | None:
    """Store + register the package; returns the artifact row (None without a project)."""
    from platform_core import artifacts
    from platform_core.storage import get_storage, project_key

    db = SessionLocal()
    try:
        pkg = db.get(BaPackageModel, session_id)
        project_id = getattr(pkg, "project_id", None)
        title = (getattr(pkg, "feature_title", None) or "BA package").strip()
    finally:
        db.close()
    if not project_id:
        return None

    digest = _content_hash(envelope)
    last = artifacts.latest("ba_package", session_id)
    if last and last["content_hash"] == digest:
        return last
    version = (last["version"] + 1) if last else 1
    key = project_key(project_id, "ba", "packages", session_id, f"ba-package-v{version}.json")
    get_storage().put(
        key,
        json.dumps(envelope, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        content_type="application/json",
    )
    row, created = artifacts.register(
        project_id=project_id,
        kind="ba_package",
        source_module="ba",
        source_ref=session_id,
        title=title,
        storage_key=key,
        content_hash=digest,
        version=version,
        meta={"correlation_id": envelope.get("correlation_id"), "feature_id": envelope.get("feature_id")},
        created_by=created_by,
    )
    if created:
        logger.info("Published BA package %s v%s -> %s", session_id, version, key)
    return row
