"""Screens of a session (HTML designer): list, read, save, versions, iframe document, screenshot.

Access follows ``designer_access``: members read, DESIGNER (or ADMIN) writes. The vendor
scripts the iframe loads are public (``/render/vendor``) because a sandboxed iframe sends
no cookies.
"""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request, Response, status

from ..core.errors import AppError, not_found
from ..designsystem.service import design_context
from ..models import ScreenVersionView, ScreenView, ScreenWrite
from ..render import build_document
from ..render.assets import inline_assets
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
    # Screen documents run in a sandboxed iframe, so their vendor scripts need
    # an absolute URL. Prefer the public origin forwarded by the gateway (this
    # matters when ngrok terminates HTTPS); retain the configured URL for direct
    # service calls that did not pass through the gateway.
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    configured_origin = request.app.state.settings.platform_public_url.rstrip("/")
    configured = urlsplit(configured_origin)
    # ngrok terminates TLS before forwarding to the local HTTP gateway. Some
    # gateway/tunnel combinations still forward ``http`` here even though the
    # browser is on the public HTTPS URL. Using that value creates mixed-content
    # script URLs inside the sandboxed screen iframe, so Tailwind never loads.
    if forwarded_host.lower().endswith((".ngrok-free.dev", ".ngrok-free.app", ".ngrok.io")):
        forwarded_proto = "https"
    if forwarded_host and forwarded_proto in {"http", "https"}:
        # Local reverse proxies often forward ``localhost`` without its
        # browser-facing port. Preserve the configured port when both hosts
        # refer to the same local machine; otherwise iframe assets fall back
        # to port 80 and fail with ERR_CONNECTION_REFUSED.
        forwarded_name = forwarded_host.rsplit(":", 1)[0].lower()
        configured_name = (configured.hostname or "").lower()
        configured_has_port = configured.port is not None
        if (":" not in forwarded_host and configured_has_port
                and forwarded_name == configured_name
                and forwarded_name in {"localhost", "127.0.0.1"}):
            forwarded_host = configured.netloc
        public_origin = f"{forwarded_proto}://{forwarded_host}"
    else:
        public_origin = configured_origin
    return public_origin + "/designer/api/v1/render/vendor/"


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
    session = await request.app.state.store.get_session(session_id)
    ds = await design_context(request.app.state.store, session)
    document = build_document(
        await inline_assets(screen.html or "", session.project_id), vendor_base=vendor_base(request), title=screen.name, theme_css=ds.theme_css, fonts=ds.fonts
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
    session = await request.app.state.store.get_session(session_id)
    ds = await design_context(request.app.state.store, session)
    result = await request.app.state.renderer.render(
        await inline_assets(screen.html or "", session.project_id), width=width or screen.width, state=state, screenshot=format, scale=scale, lint=False,
        theme_css=ds.theme_css, fonts=ds.fonts,
    )
    name = f"{screen.id}-v{screen.version}{'-' + state if state else ''}.{'jpg' if format == 'jpeg' else 'png'}"
    return Response(
        result.image or b"",
        media_type=result.mime or "image/png",
        headers={"Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"},
    )


@router.get("/sessions/{session_id}/export")
async def export_session(
    request: Request,
    session_id: UUID,
    format: Literal["fig", "zip"] = "zip",
    layout: Literal["rows", "pages"] = "rows",
) -> Response:
    """All screens of the session: ``fig`` (open in Figma) or ``zip`` (HTML prototype + PNG + design.fig).

    ``layout`` arranges the .fig: ``rows`` = one page, a row per screen; ``pages`` = a page per screen.
    """
    from ..export.bundle import export_screens

    store = request.app.state.store
    session = await store.get_session(session_id)
    if session is None:
        raise not_found("Session")
    screens = await store.list_screens(session_id, with_html=True)
    if not screens:
        raise AppError("NO_SCREENS", "Nothing to export", "The session has no screens yet.", 409)
    ds = await design_context(store, session)
    out = await export_screens(request.app.state.renderer, screens, ds, session.title, session.project_id, layout)
    data, media = (out.fig, "application/octet-stream") if format == "fig" else (out.zip, "application/zip")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", session.title).strip("-") or "design"
    return Response(data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{name}.{format}"', "Cache-Control": "no-store",
    })
