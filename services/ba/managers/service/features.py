"""FastAPI Router for Feature CRUD and Chat History endpoints.

Routes:
- POST   /api/features              — Create feature
- GET    /api/features              — List features
- GET    /api/features/{session_id} — Get feature detail
- DELETE /api/features/{session_id} — Delete feature
- POST   /api/features/{session_id}/export — Export VALIDATED package
- GET    /api/features/{session_id}/documents — Approved wiki documents
- GET    /api/features/{session_id}/history — Chat history
"""

from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from platform_core.fastapi import auth_disabled

from agents.ba_agent.constants import TIER1_SECTIONS
from factory_wiki.store import get_wiki_store
from managers.control.bpmn import can_generate_bpmn, ensure_bpmn_artifact
from managers.control.export import export_validated_package
from managers.control.session import (
    CONTROL_USER_ID,
    initial_feature_state,
    load_control_state,
    persist_control_delta,
    project_id_for_session,
)
from managers.control.touchpoints import (
    can_generate_touchpoints,
    ensure_touchpoints_artifact,
    replace_touchpoints,
)
from agents.ba_agent.section_gate import (
    SECTION_FLAG_KEYS,
    can_proceed_to_validation,
    section_is_complete,
)
from managers.control.status import (
    can_export,
    is_chat_frozen,
    is_readonly,
    normalize_feature_status,
    package_was_exported,
)
from managers.database import connection as db_connection
from managers.database.models import BaPackageModel, DesignerHandoffModel
from managers.integrations.designer.service import send_to_designer
from managers.runner_context import APP_NAME, get_session_service
from config.base_config import settings
from managers.service.schema import (
    ChatHistoryResponse,
    ChatMessageItem,
    CreateFeatureRequest,
    FeatureListItem,
    FeatureResponse,
    SectionProgress,
    TouchpointsUpdate,
    WikiDocumentHit,
    WikiDocumentList,
    WikiValidationSummary,
)
from managers.service.access import BA_ROLE, current_username, require_project
from managers.service.assets import publish_ba_package
from managers.service.state_helpers import is_user_facing_author
from managers.service.wiki_validation_status import (
    annotate_document_hit,
    summarize_validation_statuses,
    wiki_validation_snapshot,
)

logger = logging.getLogger(__name__)

USER_ID = CONTROL_USER_ID
REQUIRED_SECTIONS_TOTAL = len(TIER1_SECTIONS)

router = APIRouter(prefix="/api/features", tags=["Features"])


# ── Helpers ───────────────────────────────────────────────────


def _is_completable_from_row(sec) -> bool:
    """Recompute gate from stored flags so stale DB COMPLETED cannot lie."""
    flag_key = SECTION_FLAG_KEYS.get(sec.section_id)
    if not flag_key:
        return bool(sec.is_completable)
    return section_is_complete(
        {"flags": {flag_key: sec.flags or {}}},
        sec.section_id,
    )


def _get_db():
    """Get a synchronous DB session from the current process-wide factory."""
    return db_connection.SessionLocal()


def _build_feature_list_item(
    pkg: BaPackageModel, *, project_id: str | None = None
) -> FeatureListItem:
    """Convert DB model to list item response."""
    completed = sum(
        1
        for sec in pkg.sections
        if _is_completable_from_row(sec) and sec.section_id in TIER1_SECTIONS
    )
    sid = str(pkg.session_id)
    return FeatureListItem(
        session_id=sid,
        title=pkg.feature_title or "Untitled Feature",
        description=pkg.feature_description or "",
        project_id=project_id or project_id_for_session(sid),
        sections_completed=completed,
        sections_total=REQUIRED_SECTIONS_TOTAL,
        feature_status=normalize_feature_status(getattr(pkg, "feature_status", None)),
        created_at=pkg.created_at,
        updated_at=pkg.updated_at,
    )


# ── Feature CRUD ──────────────────────────────────────────────


@router.post("", response_model=FeatureListItem, status_code=201)
@router.post("/", response_model=FeatureListItem, status_code=201, include_in_schema=False)
async def create_feature(req: CreateFeatureRequest):
    """Create a BA feature inside a platform project (core.projects).

    Without auth (tests), a missing project_id falls back to the historical
    per-session id PRJ- + sha256(session_id)[:12].
    """
    session_id = str(uuid.uuid4())
    requested = (req.project_id or "").strip() or None
    if not auth_disabled() or requested:
        require_project(requested, BA_ROLE)
    project_id = requested or project_id_for_session(session_id)
    session_service = get_session_service()

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
        state=initial_feature_state(
            session_id,
            title=req.title,
            description=req.description,
            project_id=project_id,
        ),
    )

    db = _get_db()
    try:
        pkg = BaPackageModel(
            session_id=session_id,
            feature_title=req.title,
            feature_description=req.description,
            feature_status="DRAFT",
            project_id=requested,
            created_by=current_username(default=None),
        )
        db.add(pkg)
        db.commit()
        db.refresh(pkg)

        return FeatureListItem(
            session_id=session_id,
            title=req.title,
            description=req.description,
            project_id=project_id,
            sections_completed=0,
            sections_total=REQUIRED_SECTIONS_TOTAL,
            feature_status="DRAFT",
            created_at=pkg.created_at,
            updated_at=pkg.updated_at,
        )
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error("Failed to create feature: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("", response_model=list[FeatureListItem])
@router.get("/", response_model=list[FeatureListItem], include_in_schema=False)
async def list_features(
    project_id: str | None = Query(None, description="Platform project; required when auth is on"),
):
    """List the BA features of one project (data workspace, BA sessions)."""
    pid_filter = (project_id or "").strip() or None
    if not auth_disabled() or pid_filter:
        require_project(pid_filter)
    db = _get_db()
    try:
        query = db.query(BaPackageModel)
        if pid_filter:
            query = query.filter(BaPackageModel.project_id == pid_filter)
        packages = query.order_by(BaPackageModel.updated_at.desc()).all()
        items: list[FeatureListItem] = []
        for pkg in packages:
            control = await load_control_state(str(pkg.session_id))
            pid = str(
                pkg.project_id
                or control.get("project_id")
                or project_id_for_session(str(pkg.session_id))
            )
            items.append(_build_feature_list_item(pkg, project_id=pid))
        return items
    finally:
        db.close()


@router.get("/{session_id}", response_model=FeatureResponse)
async def get_feature(session_id: str):
    """Get feature detail with all section data."""
    db = _get_db()
    try:
        pkg = db.get(BaPackageModel, session_id)
        if not pkg:
            raise HTTPException(status_code=404, detail="Feature not found")

        sections = {}
        for sec in pkg.sections:
            sections[sec.section_id] = SectionProgress(
                section_id=sec.section_id,
                data=sec.data or {},
                flags=sec.flags or {},
                is_completable=_is_completable_from_row(sec),
            )

        control = await load_control_state(session_id)
        status = normalize_feature_status(control.get("feature_status"))
        artifacts = control.get("artifacts") or {}
        bpmn = artifacts.get("bpmn_reference")
        if isinstance(bpmn, dict) and bpmn and "bpmn_reference" not in sections:
            sections["bpmn_reference"] = SectionProgress(
                section_id="bpmn_reference",
                data=bpmn,
                flags={},
                is_completable=bool(bpmn.get("bpmn_xml_content")),
            )
        touchpoints = artifacts.get("ui_touchpoints")
        if isinstance(touchpoints, dict):
            touchpoints = touchpoints.get("ui_touchpoints") or []
        if isinstance(touchpoints, list) and touchpoints and "ui_touchpoints" not in sections:
            sections["ui_touchpoints"] = SectionProgress(
                section_id="ui_touchpoints",
                data={"ui_touchpoints": touchpoints},
                flags={},
                is_completable=True,
            )
        last_va = control.get("last_validation") or control.get("_va_result")
        last_va_dict = dict(last_va) if isinstance(last_va, dict) else None
        exported = package_was_exported(control)
        return FeatureResponse(
            session_id=str(pkg.session_id),
            title=pkg.feature_title or "Untitled Feature",
            description=pkg.feature_description or "",
            sections=sections,
            feature_status=status,
            project_id=str(
                control.get("project_id") or project_id_for_session(str(pkg.session_id))
            ),
            can_export=can_export(status, last_va_dict),
            can_proceed_to_validation=can_proceed_to_validation(control),
            package_exported=exported,
            designer_enabled=settings.designer_enabled,
            chat_frozen=is_chat_frozen(status, exported),
            open_questions=list(control.get("open_questions") or []),
            assumptions=list(control.get("assumptions") or []),
            last_validation=last_va_dict,
            can_generate_bpmn=can_generate_bpmn(control) and not is_readonly(status),
            active_user_story_id=control.get("active_user_story_id"),
            created_at=pkg.created_at,
            updated_at=pkg.updated_at,
        )
    finally:
        db.close()


@router.delete("/{session_id}", status_code=204)
async def delete_feature(session_id: str):
    """Hard-delete a BA feature regardless of status (including EXPORTED / completed)."""
    db = _get_db()
    try:
        pkg = db.get(BaPackageModel, session_id)
        if not pkg:
            raise HTTPException(status_code=404, detail="Feature not found")

        db.delete(pkg)
        db.commit()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/{session_id}/export")
async def export_feature(session_id: str):
    """Download the Common Envelope BA Package. Only when VALIDATED."""
    db = _get_db()
    try:
        pkg = db.get(BaPackageModel, session_id)
        if not pkg:
            raise HTTPException(status_code=404, detail="Feature not found")
    finally:
        db.close()
    envelope = await export_validated_package(session_id, user_id=USER_ID)
    _publish_assets(session_id, envelope)
    return envelope


def _publish_assets(session_id: str, envelope: dict) -> None:
    """Platform: every export becomes a versioned ba_package in project Assets."""
    try:
        publish_ba_package(session_id, envelope, current_username(default=None))
    except Exception:  # noqa: BLE001 — Assets must never block the BA export
        logger.exception("Publishing BA package %s to Assets failed", session_id)


@router.post("/{session_id}/designer-handoff")
async def designer_handoff(session_id: str):
    """Export the validated package and explicitly hand it to Designer."""
    if not settings.designer_enabled:
        raise HTTPException(status_code=503, detail="Designer handoff is disabled")
    envelope = await export_validated_package(session_id, user_id=USER_ID)
    _publish_assets(session_id, envelope)
    correlation_id = str(envelope.get("correlation_id") or session_id)
    db = _get_db()
    record = None
    try:
        pkg = db.get(BaPackageModel, session_id)
        project_id = getattr(pkg, "project_id", None)
        record = (
            db.query(DesignerHandoffModel)
            .filter_by(feature_id=session_id, correlation_id=correlation_id)
            .first()
        )
        if record and record.response_payload:
            cached = dict(record.response_payload)
            cached["status"] = record.status.lower()
            # Rebuild the browser URL from current configuration so old handoffs stay valid.
            cached.pop("openpencil_url", None)
            if record.designer_session_id:
                query = f"project={project_id}&" if project_id else ""
                cached["designer_url"] = (
                    settings.designer_ui_base_url.rstrip("/")
                    + f"/?{query}session={record.designer_session_id}"
                )
            return cached
        if record is None:
            record = DesignerHandoffModel(
                feature_id=session_id,
                correlation_id=correlation_id,
                status="CREATING",
                project_id=project_id,
            )
            db.add(record)
        else:
            record.status = "CREATING"
            record.error_message = None
        db.commit()
    finally:
        db.close()
    try:
        handoff = await send_to_designer(
            envelope,
            base_url=settings.designer_base_url,
            timeout_seconds=settings.designer_timeout_seconds,
            shared_secret=settings.designer_shared_secret,
            project_id=project_id,
            requested_by=current_username(default=None),
        )
    except Exception as error:  # noqa: BLE001
        db = _get_db()
        try:
            failed = (
                db.query(DesignerHandoffModel)
                .filter_by(feature_id=session_id, correlation_id=correlation_id)
                .first()
            )
            if failed:
                failed.status = "FAILED"
                failed.error_message = str(error)[:2000]
                db.commit()
        finally:
            db.close()
        logger.exception("Designer handoff failed for %s", session_id)
        raise HTTPException(status_code=502, detail=f"Designer handoff failed: {error}") from error
    response = handoff["response"]
    designer_url = str(response.get("designer_url") or "")
    if designer_url.startswith("/"):
        designer_url = settings.designer_ui_base_url.rstrip("/") + designer_url
    result = {
        "status": response.get("status", "queued"),
        "feature_id": session_id,
        "correlation_id": response.get("correlation_id"),
        "handoff_id": response.get("handoff_id"),
        "designer_session_id": response.get("session_id"),
        "designer_run_id": response.get("run_id"),
        "designer_url": designer_url,
    }
    db = _get_db()
    try:
        saved = (
            db.query(DesignerHandoffModel)
            .filter_by(feature_id=session_id, correlation_id=correlation_id)
            .first()
        )
        if saved:
            saved.handoff_id = str(result.get("handoff_id") or "")
            saved.designer_session_id = str(result.get("designer_session_id") or "")
            saved.designer_run_id = str(result.get("designer_run_id") or "")
            saved.designer_url = designer_url
            saved.status = "QUEUED"
            saved.request_payload = handoff.get("request")
            saved.response_payload = result
            db.commit()
    finally:
        db.close()
    return result


@router.get("/{session_id}/designer-handoff")
async def get_designer_handoff(session_id: str):
    """Return the persisted handoff link/status for a BA feature."""
    db = _get_db()
    try:
        record = (
            db.query(DesignerHandoffModel)
            .filter_by(feature_id=session_id)
            .order_by(DesignerHandoffModel.id.desc())
            .first()
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Designer handoff not found")
        return {
            "feature_id": record.feature_id,
            "correlation_id": record.correlation_id,
            "handoff_id": record.handoff_id,
            "designer_session_id": record.designer_session_id,
            "designer_run_id": record.designer_run_id,
            "designer_url": record.designer_url,
            "status": record.status.lower(),
            "error_message": record.error_message,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
    finally:
        db.close()


@router.get("/{session_id}/bpmn")
async def download_bpmn(session_id: str, regenerate: bool = False):
    """Download BPMN XML generated from the workflow section (post-UC)."""
    db = _get_db()
    try:
        pkg = db.get(BaPackageModel, session_id)
        if not pkg:
            raise HTTPException(status_code=404, detail="Feature not found")
    finally:
        db.close()
    state = await load_control_state(session_id)
    artifacts = state.get("artifacts") or {}
    existing = artifacts.get("bpmn_reference") if isinstance(artifacts.get("bpmn_reference"), dict) else {}
    xml = existing.get("bpmn_xml_content") if isinstance(existing, dict) else None
    if xml and not regenerate:
        filename = existing.get("bpmn_xml_path") or f"ba-{session_id}.bpmn"
        return Response(
            content=xml,
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    if is_readonly(state.get("feature_status")) and regenerate:
        raise HTTPException(status_code=409, detail="Feature is EXPORTED and read-only")
    if not can_generate_bpmn(state):
        raise HTTPException(
            status_code=409,
            detail=(
                "BPMN requires sequential FD → BR → WF → UC complete "
                "(Group 2 unlocks after User Stories)."
            ),
        )
    artifact = ensure_bpmn_artifact(state, force=regenerate)
    if not artifact or not artifact.get("bpmn_xml_content"):
        raise HTTPException(status_code=500, detail="BPMN generation produced no XML")
    if not is_readonly(state.get("feature_status")):
        await persist_control_delta(
            session_id,
            {"artifacts": state.get("artifacts") or {}},
            user_id=USER_ID,
        )
    filename = artifact.get("bpmn_xml_path") or f"ba-{session_id}.bpmn"
    return Response(
        content=artifact["bpmn_xml_content"],
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/{session_id}/touchpoints")
async def update_touchpoints(session_id: str, body: TouchpointsUpdate):
    """Edit the BA conclusion UI touchpoints list (Designer handoff input)."""
    db = _get_db()
    try:
        pkg = db.get(BaPackageModel, session_id)
        if not pkg:
            raise HTTPException(status_code=404, detail="Feature not found")
    finally:
        db.close()
    state = await load_control_state(session_id)
    status = normalize_feature_status(state.get("feature_status"))
    if is_readonly(status):
        raise HTTPException(status_code=409, detail="Feature is EXPORTED and read-only")
    if not can_generate_touchpoints(state):
        raise HTTPException(
            status_code=409,
            detail="UI touchpoints require sequential FD → BR → WF → UC complete",
        )
    items = replace_touchpoints(state, list(body.ui_touchpoints or []))
    await persist_control_delta(
        session_id,
        {"artifacts": state.get("artifacts") or {}},
        user_id=USER_ID,
    )
    return {"session_id": session_id, "ui_touchpoints": items}


@router.get("/{session_id}/documents", response_model=WikiDocumentList)
async def list_feature_documents(session_id: str, q: str = ""):
    """Search approved wiki pages: this feature's project_id + company namespace.

    Live list = human-approved pages. Per-item ``validation_status`` is tagged
    against ``last_validation`` evidence/findings (pass | fail | unchecked).
    Newly approved pages after last Validate stay unchecked — not silent pass.
    """
    db = _get_db()
    try:
        pkg = db.get(BaPackageModel, session_id)
        if not pkg:
            raise HTTPException(status_code=404, detail="Feature not found")
    finally:
        db.close()
    control = await load_control_state(session_id)
    project_id = str(
        control.get("project_id") or project_id_for_session(session_id)
    )
    store = get_wiki_store()
    try:
        query = (q or "").strip()
        if query:
            hits = store.search(
                query,
                project_id=project_id,
                agent_name="ba-agent",
                limit=50,
            )
        else:
            hits = store.list_approved(project_id=project_id, agent_name="ba-agent")
    finally:
        store.close()

    last_va = control.get("last_validation") or control.get("_va_result")
    last_va_dict = dict(last_va) if isinstance(last_va, dict) else None
    snapshot = wiki_validation_snapshot(last_va_dict)
    annotated = [annotate_document_hit(hit, snapshot=snapshot) for hit in hits]
    docs = [WikiDocumentHit(**hit) for hit in annotated]
    company = [d for d in docs if (d.namespace or "") == "company"]
    project = [d for d in docs if (d.namespace or "") != "company"]
    summary = summarize_validation_statuses(
        [d.validation_status for d in docs],
        snapshot=snapshot,
    )
    return WikiDocumentList(
        session_id=session_id,
        project_id=project_id,
        documents=docs,
        company_documents=company,
        project_documents=project,
        wiki_validation=WikiValidationSummary(**summary),
    )


# ── Chat History ──────────────────────────────────────────────


@router.get("/{session_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    section: str | None = None,
):
    """Get chat history by reconstructing from ADK session events.

    When ``section`` is set, only keep turns whose agent reply came from that
    section's discussion author (so BR does not re-render the whole FD chat).
    """
    from agents.ba_agent.constants import (
        SECTION_DISCUSSION_AUTHOR,
        SECTION_VALIDATION,
        VA_CHAT_AUTHORS,
    )

    session_service = get_session_service()

    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
    )

    allowed_author = SECTION_DISCUSSION_AUTHOR.get(section or "") if section else None

    messages: list[ChatMessageItem] = []
    pending_user: str | None = None
    if session and session.events:
        for event in session.events:
            if not event.content or not event.content.parts:
                continue

            text_parts = [p.text for p in event.content.parts if p.text]
            if not text_parts:
                continue
            full_text = "".join(text_parts)
            author = getattr(event, "author", None)

            if event.content.role == "user":
                pending_user = full_text
                continue

            if not is_user_facing_author(author):
                continue

            if section == SECTION_VALIDATION or allowed_author in VA_CHAT_AUTHORS:
                if author not in VA_CHAT_AUTHORS:
                    pending_user = None
                    continue
            elif allowed_author and author != allowed_author:
                pending_user = None
                continue

            if pending_user is not None:
                messages.append(ChatMessageItem(sender="user", text=pending_user))
                pending_user = None
            messages.append(ChatMessageItem(sender="agent", text=full_text))

    # Keep the last user turn even when the agent/API errored before a reply.
    # Otherwise a failed turn drops that message (and a reload looks like a wipe).
    if pending_user is not None:
        messages.append(ChatMessageItem(sender="user", text=pending_user))

    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages,
    )
