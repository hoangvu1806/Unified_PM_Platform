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
        if not artifacts.latest("bpmn", session_id):
            _publish_bpmn(project_id, session_id, title, envelope, last, created_by)  # packages from before BPMN assets
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
        _publish_bpmn(project_id, session_id, title, envelope, row, created_by)
    return row


def _publish_bpmn(
    project_id: str, session_id: str, title: str, envelope: dict[str, Any], package: dict[str, Any], created_by: str | None
) -> None:
    """The package's reference BPMN as its own artifact (same version, linked to the package)."""
    from platform_core import artifacts
    from platform_core.storage import get_storage, project_key

    ref = ((envelope.get("payload") or {}).get("artifacts") or {}).get("bpmn_reference") or {}
    xml = str(ref.get("bpmn_xml_content") or "").strip()
    if not xml:
        return
    try:
        version = package["version"]
        key = project_key(project_id, "ba", "bpmn", session_id, f"bpmn-v{version}.bpmn")
        get_storage().put(key, xml.encode("utf-8"), content_type="application/xml")
        artifacts.register(
            project_id=project_id,
            kind="bpmn",
            source_module="ba",
            source_ref=session_id,
            title=f"{title} — BPMN",
            storage_key=key,
            content_hash=hashlib.sha256(xml.encode("utf-8")).hexdigest(),
            version=version,
            derived_from_id=package["id"],
            meta={"feature_id": session_id},
            created_by=created_by,
        )
        logger.info("Published BPMN %s v%s -> %s", session_id, version, key)
    except Exception:  # noqa: BLE001
        logger.exception("Publishing BPMN for %s failed", session_id)
