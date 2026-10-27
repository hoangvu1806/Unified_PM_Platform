"""Design systems: import from a Figma .fig, list, inspect, gallery, snippets, choose per session.

A design system belongs to a project (members read, DESIGNER/ADMIN import and delete);
``default`` is the built-in neutral theme without components.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request, Response, status
from platform_core.fastapi import auth_disabled, require_project

from ..core.errors import AppError, not_found
from ..designsystem.gallery import gallery_fragment
from ..designsystem.service import DEFAULT_CONTEXT, run_import
from ..models import DEFAULT_DESIGN_SYSTEM, DesignSystemDetail, DesignSystemView, SessionDesignSystem, SessionView
from ..render import build_document
from ..storage import layout
from .access import DESIGNER_ROLE, current_username
from .screens import vendor_base

router = APIRouter(prefix="/api/v1")
MAX_FIG_BYTES = 100 * 1024 * 1024
GALLERY_PAGE = 120
_imports: set[asyncio.Task[None]] = set()


def _require(project_id: str | None, role: str | None = None) -> None:
    if not auth_disabled() or project_id:
        require_project(project_id, role)


def _default_view() -> DesignSystemView:
    return DesignSystemView(id=DEFAULT_DESIGN_SYSTEM, name=DEFAULT_CONTEXT.name, summary={"components": 0})


async def _get(request: Request, ds_id: str) -> DesignSystemDetail:
    if ds_id == DEFAULT_DESIGN_SYSTEM:
        return DesignSystemDetail(
            **_default_view().model_dump(), theme_css=DEFAULT_CONTEXT.theme_css, fonts=DEFAULT_CONTEXT.fonts
        )
    ds = await request.app.state.store.get_design_system(ds_id)
    if ds is None:
        raise not_found("Design system")
    _require(ds.project_id)
    return ds


@router.get("/design-systems", response_model=list[DesignSystemView])
async def list_design_systems(request: Request, project_id: str | None = Query(None)) -> list[DesignSystemView]:
    _require(project_id)
    return [_default_view(), *await request.app.state.store.list_design_systems(project_id)]


@router.post("/design-systems", response_model=DesignSystemView, status_code=status.HTTP_202_ACCEPTED)
async def import_design_system(
    request: Request,
    project_id: str | None = Query(None),
    name: str = Query(..., min_length=1, max_length=120),
    filename: str = Query("design-system.fig", max_length=240),
) -> DesignSystemView:
    """Body: the raw .fig bytes (``application/octet-stream``). Import runs in the background."""
    _require(project_id, DESIGNER_ROLE)
    data = await request.body()
    if not data:
        raise AppError("FIG_EMPTY", "Empty upload", "Send the .fig file as the request body.", 422)
    if len(data) > MAX_FIG_BYTES:
        raise AppError("FIG_TOO_LARGE", "File is too large", "Use a .fig smaller than 100 MB.", 413)
    if not (data[:2] == b"PK" or data[:8] == b"fig-kiwi"):
        raise AppError("FIG_INVALID", "Not a Figma file", "Export it from Figma with File → Save local copy.", 422)
    ds_id = f"ds-{uuid4().hex[:12]}"
    source_key = None
    try:
        from platform_core.storage import get_storage

        source_key = layout.design_system_source_key(project_id, ds_id)
        get_storage().put(source_key, data, content_type="application/octet-stream")
    except Exception:  # noqa: BLE001 — the source copy is a convenience; the import works from memory
        source_key = None
    store = request.app.state.store
    await store.create_design_system(
        ds_id, name=name.strip(), project_id=project_id, source_name=filename, source_key=source_key,
        created_by=current_username(),
    )
    task = asyncio.create_task(run_import(store, ds_id, data, name.strip()))
    _imports.add(task)
    task.add_done_callback(_imports.discard)
    return DesignSystemView(id=ds_id, name=name.strip(), project_id=project_id, status="importing", source_name=filename)


@router.get("/design-systems/{ds_id}", response_model=DesignSystemDetail)
async def get_design_system(request: Request, ds_id: str) -> DesignSystemDetail:
    return await _get(request, ds_id)


@router.delete("/design-systems/{ds_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_design_system(request: Request, ds_id: str) -> Response:
    if ds_id == DEFAULT_DESIGN_SYSTEM:
        raise AppError("DESIGN_SYSTEM_BUILTIN", "Built-in design system", "The default design system cannot be deleted.", 409)
    ds = await _get(request, ds_id)
    _require(ds.project_id, DESIGNER_ROLE)
    await request.app.state.store.delete_design_system(ds_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/design-systems/{ds_id}/snippets/{variant_id}")
async def get_snippet(request: Request, ds_id: str, variant_id: str) -> dict[str, str]:
    await _get(request, ds_id)
    snippets = await request.app.state.store.get_snippets(ds_id, [variant_id])
    if variant_id not in snippets:
        raise not_found("Component variant")
    return {"id": variant_id, "html": snippets[variant_id]}


@router.get("/design-systems/{ds_id}/gallery")
async def gallery_document(
    request: Request, ds_id: str, page: int = Query(0, ge=0), q: str = Query("", max_length=80)
) -> Response:
    """HTML document of the converted components (paged) for review in the design page."""
    ds = await _get(request, ds_id)
    needle = q.strip().lower()
    components = [c for c in ds.components if not needle or needle in c["name"].lower() or needle in c["id"]]
    chosen, count = [], 0
    for component in components:
        if count >= (page + 1) * GALLERY_PAGE:
            break
        n = len(component["variants"])
        if count + n > page * GALLERY_PAGE:
            chosen.append(component)
        count += n
    ids = [v["id"] for c in chosen for v in c["variants"]]
    snippets = await request.app.state.store.get_snippets(ds_id, ids)
    fragment = gallery_fragment(chosen, snippets, ds.name)
    document = build_document(fragment, vendor_base=vendor_base(request), theme_css=ds.theme_css, fonts=ds.fonts,
                              title=ds.name)
    return Response(document, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


@router.put("/sessions/{session_id}/design-system", response_model=SessionView)
async def set_session_design_system(request: Request, session_id: UUID, body: SessionDesignSystem) -> SessionView:
    store = request.app.state.store
    session = await store.get_session(session_id)
    if session is None:
        raise not_found("Session")
    if body.design_system_id != DEFAULT_DESIGN_SYSTEM:
        ds = await _get(request, body.design_system_id)
        if ds.project_id not in (None, session.project_id):
            raise AppError("DESIGN_SYSTEM_PROJECT", "Design system of another project", ds.id, 409)
        if ds.status != "ready":
            raise AppError("DESIGN_SYSTEM_NOT_READY", "Design system is not ready", ds.status, 409)
    await store.set_session_design_system(
        session_id, None if body.design_system_id == DEFAULT_DESIGN_SYSTEM else body.design_system_id
    )
    return await store.get_session(session_id)
