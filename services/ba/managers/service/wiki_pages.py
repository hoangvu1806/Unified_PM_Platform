"""Human-only wiki ingest / list / approve / demote / delete / clear on MVP SQLite.

BA and VA read approved pages through ``factory_wiki.store``. This router is
the write path for humans (upload → draft → approve, demote/delete, clear).
Agents never approve, demote, delete, or clear.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from factory_wiki.paths import ensure_manifest, ensure_mvp_importable, wiki_service_root
from factory_wiki.reset import WikiResetError, reset_wiki_store
from factory_wiki.store import human_actor

router = APIRouter(prefix="/api/wiki", tags=["Wiki Knowledge"])


def _raise_wiki(exc: Exception) -> None:
    http_status = int(getattr(exc, "http_status", 400) or 400)
    payload = exc.as_dict() if hasattr(exc, "as_dict") else {"message": str(exc)}
    raise HTTPException(status_code=http_status, detail=payload) from exc


def _wiki_service():
    ensure_mvp_importable()
    from wiki.service import WikiService

    root = wiki_service_root()
    ensure_manifest(root)
    return WikiService(root)


def _page_row(page: Any) -> dict[str, Any]:
    body = str(getattr(page, "body", "") or "")
    return {
        "page_id": page.page_id,
        "title": page.title,
        "status": page.status,
        "namespace": page.namespace,
        "project_id": page.project_id,
        "bucket_id": page.bucket_id,
        "version": page.version,
        "abbrev": page.abbrev,
        "updated_at": page.updated_at,
        "snippet": body[:160] + ("..." if len(body) > 160 else ""),
    }


def _visible(page: Any, project_id: str | None) -> bool:
    """Company pages are shared; project pages only match the requested project_id."""
    pid = (project_id or "").strip()
    if not pid:
        # Refuse unscoped listing — never dump every project's private pages.
        return getattr(page, "namespace", "") == "company"
    if getattr(page, "namespace", "") == "company":
        return True
    return (page.project_id or "") == pid


@router.get("/pages")
def list_wiki_pages(
    status: str | None = Query(
        None,
        description="Optional filter: draft | proposed | approved (omit = all visible)",
    ),
    project_id: str = Query(
        ...,
        description=(
            "Required BA project_id (PRJ- + 12 hex of sha256(session_id) from the feature). "
            "Returns company pages plus this project's private pages. No MES default."
        ),
    ),
):
    """List wiki pages scoped to project_id (+ shared company namespace)."""
    svc = _wiki_service()
    try:
        if status in {"draft", "proposed"}:
            pages = svc.list_pages(status=status)
        elif status == "approved":
            pages = svc.list_pages(status="approved")
        else:
            pages = (
                svc.list_pages(status="draft")
                + svc.list_pages(status="proposed")
                + svc.list_pages(status="approved")
            )
        visible = [p for p in pages if _visible(p, project_id)]
        drafts = [p for p in visible if p.status in {"draft", "proposed"}]
        approved = [p for p in visible if p.status == "approved"]
        company_approved = [
            _page_row(p) for p in approved if getattr(p, "namespace", "") == "company"
        ]
        project_approved = [
            _page_row(p) for p in approved if getattr(p, "namespace", "") != "company"
        ]
        company_drafts = [
            _page_row(p) for p in drafts if getattr(p, "namespace", "") == "company"
        ]
        project_drafts = [
            _page_row(p) for p in drafts if getattr(p, "namespace", "") != "company"
        ]
        return {
            "project_id": project_id,
            "data_root": str(wiki_service_root()),
            "import_flow": "upload → draft → human approve → BA/VA can fetch",
            "drafts": [_page_row(p) for p in drafts],
            "approved": [_page_row(p) for p in approved],
            "company_drafts": company_drafts,
            "project_drafts": project_drafts,
            "company_approved": company_approved,
            "project_approved": project_approved,
        }
    finally:
        svc.close()


@router.post("/sources")
async def upload_wiki_source(
    file: UploadFile = File(...),
    namespace: str = Form(
        "project",
        description="company = org-wide shared wiki; project = private to project_id",
    ),
    project_id: str = Form(
        "",
        description=(
            "Required when namespace=project: feature hashed PRJ-* id. "
            "Ignored for company uploads (no shared MES default)."
        ),
    ),
    actor: str = Form("ba.lead", description="Human actor id for audit"),
    sort_mode: str = Form("auto", description="heuristic | llm | auto | both"),
):
    """Human ingest. Same WikiService / SQLite as the Wiki MVP HTTP UI."""
    if namespace not in {"company", "project"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "COMMON_SCHEMA_INVALID", "message": "namespace must be company or project"},
        )
    if namespace == "project" and not (project_id or "").strip():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "COMMON_SCHEMA_INVALID",
                "message": "project_id is required when namespace=project",
            },
        )
    # Company wiki is org-scoped — do not bind private project_id on the page.
    scoped_project = None if namespace == "company" else ((project_id or "").strip() or None)
    svc = _wiki_service()
    try:
        ensure_mvp_importable()
        from wiki.models import WikiError

        who = human_actor(scoped_project or project_id or "PRJ-COMPANY")
        who = who.model_copy(update={"actor": actor or "ba.lead"})
        data = await file.read()
        mode = (sort_mode or "auto").strip().lower()
        if mode not in {"heuristic", "llm", "auto", "both"}:
            mode = "auto"
        try:
            result = svc.ingest_source(
                who,
                filename=file.filename or "upload.pdf",
                data=data,
                namespace=namespace,
                project_id=scoped_project,
                sort_mode=mode,
            )
        except WikiError as exc:
            _raise_wiki(exc)
        return {
            "ok": True,
            "import_flow": "upload → draft → human approve → BA/VA can fetch",
            **result,
        }
    finally:
        svc.close()


@router.post("/pages/{page_id}/approve")
def approve_wiki_page(
    page_id: str,
    actor: str = Form("ba.lead", description="Human actor id for audit"),
    project_id: str = Form(
        ...,
        description="Required feature project_id (hashed PRJ-*); no MES default",
    ),
):
    """Human-only approve. Agents are never constructed on this path."""
    if not (project_id or "").strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "COMMON_SCHEMA_INVALID", "message": "project_id is required"},
        )
    svc = _wiki_service()
    try:
        ensure_mvp_importable()
        from wiki.models import WikiError

        who = human_actor(project_id.strip())
        who = who.model_copy(update={"actor": actor or "ba.lead", "actor_type": "human"})
        try:
            page = svc.approve_page(who, page_id)
        except WikiError as exc:
            _raise_wiki(exc)
        return {"ok": True, **_page_row(page)}
    finally:
        svc.close()


@router.post("/pages/{page_id}/demote")
def demote_wiki_page(
    page_id: str,
    actor: str = Form("ba.lead", description="Human actor id for audit"),
    project_id: str = Form(
        ...,
        description="Required feature project_id (hashed PRJ-*); no MES default",
    ),
):
    """Human-only: approved → draft. Prefer over delete when clearing V-WIKI pairs."""
    if not (project_id or "").strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "COMMON_SCHEMA_INVALID", "message": "project_id is required"},
        )
    svc = _wiki_service()
    try:
        ensure_mvp_importable()
        from wiki.models import WikiError

        who = human_actor(project_id.strip())
        who = who.model_copy(update={"actor": actor or "ba.lead", "actor_type": "human"})
        try:
            page = svc.demote_page(who, page_id)
        except WikiError as exc:
            _raise_wiki(exc)
        return {
            "ok": True,
            "hint": "Page is draft again — invisible to BA/VA. Re-Validate after removing the violator.",
            **_page_row(page),
        }
    finally:
        svc.close()


@router.post("/pages/{page_id}/delete")
def delete_wiki_page(
    page_id: str,
    actor: str = Form("ba.lead", description="Human actor id for audit"),
    project_id: str = Form(
        ...,
        description="Required feature project_id (hashed PRJ-*); no MES default",
    ),
):
    """Human-only hard delete. Prefer demote when unsure."""
    if not (project_id or "").strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "COMMON_SCHEMA_INVALID", "message": "project_id is required"},
        )
    svc = _wiki_service()
    try:
        ensure_mvp_importable()
        from wiki.models import WikiError

        who = human_actor(project_id.strip())
        who = who.model_copy(update={"actor": actor or "ba.lead", "actor_type": "human"})
        try:
            result = svc.delete_page(who, page_id)
        except WikiError as exc:
            _raise_wiki(exc)
        return {
            "ok": True,
            "hint": "Page deleted. Re-Validate BA after removing the violator.",
            "actor": actor or "ba.lead",
            **result,
        }
    finally:
        svc.close()


CLEAR_CONFIRM_TOKEN = "CLEAR"


@router.post("/clear")
def clear_wiki_store(
    confirm: str = Form(...),
    actor: str = Form("ba.lead"),
):
    """Human-only wipe of wiki.db (pages, sources, blobs) — never BA/ADK files.

    Not a BA/VA tool — wiki.html only. Refuses if the target SQLite contains
    ``ba_packages`` / ADK session tables, and never unlinks those database files.
    """
    if (confirm or "").strip().upper() != CLEAR_CONFIRM_TOKEN:
        raise HTTPException(
            status_code=400,
            detail="confirm must be CLEAR — this deletes all wiki pages, drafts, sources, blobs",
        )
    try:
        info = reset_wiki_store()
    except WikiResetError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "ok": True,
        "cleared": True,
        "import_flow": "upload → draft → human approve → BA/VA can fetch",
        "pages": info.get("pages", 0),
        "sources": info.get("sources", 0),
        "removed_blobs": info.get("removed_blobs", 0),
        "wiki_db": info.get("wiki_db"),
        "actor": actor or "ba.lead",
    }
