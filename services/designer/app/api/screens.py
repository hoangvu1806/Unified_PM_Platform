"""Screens of a session (HTML designer): list, read, save, versions, iframe document, screenshot.

Access follows ``designer_access``: members read, DESIGNER (or ADMIN) writes. The vendor
scripts the iframe loads are public (``/render/vendor``) because a sandboxed iframe sends
no cookies.
"""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from ..core.errors import AppError, not_found
from ..designsystem.service import design_context
from ..models import ScreenVersionView, ScreenView, ScreenWrite
from ..render import build_document
from ..render.document import VENDOR_DIR
from .access import current_username

router = APIRouter(prefix="/api/v1")

SCREEN_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
VENDOR_FILES = {p.name for p in VENDOR_DIR.glob("*.js")}


def _screen_id(value: str) -> str:
    if not SCREEN_ID.fullmatch(value):
        raise AppError("SCREEN_ID_INVALID", "Invalid screen id", "Use lowercase letters, digits and '-'.", 422)
    return value


async def _session(request: Request, session_id: UUID) -> None:
    if not await request.app.state.store.get_session(session_id):
        raise not_found("Session")


async def _screen(request: Request, session_id: UUID, screen_id: str, version: int | None = None) -> ScreenView:
    await _session(request, session_id)
    screen = await request.app.state.store.get_screen(session_id, _screen_id(screen_id), version)
    if screen is None:
        raise not_found("Screen")
    return screen


def vendor_base(request: Request) -> str:
    return request.app.state.settings.platform_public_url.rstrip("/") + "/designer/api/v1/render/vendor/"


@router.get("/render/vendor/{name}")
async def vendor_file(name: str) -> Response:
    if name not in VENDOR_FILES:
        raise not_found("Vendor file")
    return Response(
        (VENDOR_DIR / name).read_bytes(),
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=86400", "Access-Control-Allow-Origin": "*"},
    )


@router.get("/sessions/{session_id}/screens", response_model=list[ScreenView])
async def list_screens(request: Request, session_id: UUID) -> list[ScreenView]:
    await _session(request, session_id)
    return await request.app.state.store.list_screens(session_id)


@router.get("/sessions/{session_id}/screens/{screen_id}", response_model=ScreenView)
async def get_screen(request: Request, session_id: UUID, screen_id: str, version: int | None = None) -> ScreenView:
    return await _screen(request, session_id, screen_id, version)


@router.put("/sessions/{session_id}/screens/{screen_id}", response_model=ScreenView)
async def save_screen(request: Request, session_id: UUID, screen_id: str, body: ScreenWrite) -> ScreenView:
    """A designer's manual edit (code view in the design page); the agent saves through the store."""
    await _session(request, session_id)
    return await request.app.state.store.save_screen(
        session_id, _screen_id(screen_id), body, updated_by=current_username()
    )


@router.delete("/sessions/{session_id}/screens/{screen_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_screen(request: Request, session_id: UUID, screen_id: str) -> Response:
    await _session(request, session_id)
    if not await request.app.state.store.delete_screen(session_id, _screen_id(screen_id)):
        raise not_found("Screen")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/{session_id}/screens/{screen_id}/versions", response_model=list[ScreenVersionView])
async def screen_versions(request: Request, session_id: UUID, screen_id: str) -> list[ScreenVersionView]:
    await _screen(request, session_id, screen_id)
    return await request.app.state.store.list_screen_versions(session_id, screen_id)


@router.get("/sessions/{session_id}/screens/{screen_id}/document")
async def screen_document(request: Request, session_id: UUID, screen_id: str, version: int | None = None) -> Response:
    """The full HTML document for the design iframe (``srcdoc``)."""
    screen = await _screen(request, session_id, screen_id, version)
    ds = await design_context(request.app.state.store, await request.app.state.store.get_session(session_id))
    document = build_document(
        screen.html or "", vendor_base=vendor_base(request), title=screen.name, theme_css=ds.theme_css, fonts=ds.fonts
    )
    return Response(document, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


@router.get("/sessions/{session_id}/screens/{screen_id}/screenshot")
async def screen_screenshot(
    request: Request,
    session_id: UUID,
    screen_id: str,
    version: int | None = None,
    state: str | None = Query(None, max_length=60),
    width: int | None = Query(None, ge=320, le=2560),
    format: Literal["png", "jpeg"] = "png",
    scale: float = Query(1, ge=1, le=3),
) -> Response:
    screen = await _screen(request, session_id, screen_id, version)
    ds = await design_context(request.app.state.store, await request.app.state.store.get_session(session_id))
    result = await request.app.state.renderer.render(
        screen.html or "", width=width or screen.width, state=state, screenshot=format, scale=scale, lint=False,
        theme_css=ds.theme_css, fonts=ds.fonts,
    )
    name = f"{screen.id}-v{screen.version}{'-' + state if state else ''}.{'jpg' if format == 'jpeg' else 'png'}"
    return Response(
        result.image or b"",
        media_type=result.mime or "image/png",
        headers={"Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"},
    )
