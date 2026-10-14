import asyncio
import base64
import binascii
import json
import re
import struct
import unicodedata
from pathlib import Path
from typing import Any, Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, HttpUrl

from ..attachments.parser import parse_bpmn_document, parse_json_document, parse_text_document
from ..core.config import designer_asset_dir
from ..core.errors import AppError, not_found
from ..core.llm import STRUCTURED_PARSER_VERSION
from ..models import (
    DesignSystemView,
    OpenPencilDocumentView,
    OpenPencilProfile,
    Platform,
    ReviewCreate,
    RunArtifacts,
    RunCreate,
    RunRetry,
    RunView,
    SessionCreate,
    SessionView,
    SessionWorkspaceUpdate,
    ExactAsset,
)
from ..openpencil.client import OpenPencilCapability

router = APIRouter(prefix="/api/v1")


class McpProbeRequest(BaseModel):
    endpoint: HttpUrl


class NamedMcpRequest(McpProbeRequest):
    name: str = Field(min_length=1, max_length=120)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)
    screen_name_hint: str = Field(default="", max_length=120)
    platform_hint: Platform = "responsive"
    style_hint: str | None = None
    library_ids: list[str] = Field(default_factory=list)
    mcp_profile: OpenPencilProfile | None = None
    assets: list[ExactAsset] = Field(default_factory=list, max_length=4)


class AttachmentParseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    mime_type: str = Field(default="", max_length=120)
    data_base64: str = Field(min_length=1, max_length=12_000_000)


class AttachmentParseResult(BaseModel):
    name: str
    kind: str
    markdown: str
    truncated: bool = False
    asset: ExactAsset | None = None


class ImageAttachmentAnalysis(BaseModel):
    summary: str = Field(min_length=1, max_length=1_500)
    visible_text: list[str] = Field(default_factory=list, max_length=60)
    ui_elements: list[str] = Field(default_factory=list, max_length=40)
    requirements_and_states: list[str] = Field(default_factory=list, max_length=40)
    visual_role: str = Field(default="image", max_length=120)
    dominant_colors: list[str] = Field(default_factory=list, max_length=8)
    background_type: str = Field(default="unknown", max_length=80)
    recommended_fit: str = Field(default="contain", max_length=20)
    recommended_placement: str = Field(default="content area", max_length=240)
    placement_reason: str = Field(default="", max_length=600)
    safe_padding_percent: int = Field(default=0, ge=0, le=40)


IMAGE_SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".yaml", ".yml"}
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024

def _asset_path(asset_id: str) -> Path:
    # Uploaded bytes live in the shared platform storage volume.
    return designer_asset_dir() / asset_id


def _standard_asset_id(name: str, suffix: str) -> str:
    stem = unicodedata.normalize("NFKD", Path(name).stem)
    stem = stem.encode("ascii", "ignore").decode("ascii").casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:40] or "image"
    extension = suffix.lstrip(".").replace("jpeg", "jpg") or "img"
    return f"{slug}-{extension}-{uuid4().hex[:12]}"


def _image_size(raw: bytes) -> tuple[int, int] | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        return struct.unpack(">II", raw[16:24])
    if raw.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 < len(raw):
            if raw[offset] != 0xFF:
                offset += 1
                continue
            marker = raw[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(raw):
                break
            length = int.from_bytes(raw[offset : offset + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if offset + 7 <= len(raw):
                    return (
                        int.from_bytes(raw[offset + 5 : offset + 7], "big"),
                        int.from_bytes(raw[offset + 3 : offset + 5], "big"),
                    )
                break
            if length < 2:
                break
            offset += length
    return None


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "llmConfigured": bool(settings.api_key and settings.base_url),
        "model": settings.llm_model,
        "structuredParser": STRUCTURED_PARSER_VERSION,
        "apiVersion": "v1",
    }


@router.post("/attachments/parse", response_model=AttachmentParseResult)
async def parse_attachment(
    request: Request, body: AttachmentParseRequest
) -> AttachmentParseResult:
    try:
        raw = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise AppError("ATTACHMENT_INVALID", "Invalid attachment", "Invalid base64 data.", 422) from error
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise AppError(
            "ATTACHMENT_TOO_LARGE",
            "Attachment is too large",
            "Use a file smaller than 8 MB.",
            413,
        )
    suffix = Path(body.name).suffix.casefold()
    safe_name = Path(body.name).name
    try:
        if suffix == ".json":
            parsed = parse_json_document(raw)
            return AttachmentParseResult(
                name=safe_name,
                kind="json",
                markdown=parsed.markdown,
                truncated=parsed.truncated,
            )
        if suffix in {".bpmn", ".bpmn2"}:
            parsed = parse_bpmn_document(raw)
            return AttachmentParseResult(
                name=safe_name,
                kind="bpmn",
                markdown=parsed.markdown,
                truncated=parsed.truncated,
            )
        if suffix in TEXT_SUFFIXES:
            parsed = parse_text_document(raw, suffix)
            return AttachmentParseResult(
                name=safe_name,
                kind="text",
                markdown=parsed.markdown,
                truncated=parsed.truncated,
            )
        if suffix in IMAGE_SUFFIXES:
            mime_type = IMAGE_SUFFIXES[suffix]
            asset_id = _standard_asset_id(safe_name, suffix)
            _asset_path(asset_id).write_bytes(raw)
            analysis = await request.app.state.llm.structured(
                prompt=(
                    "Inspect this attached image as input to a UI design agent. "
                    "Extract visible copy, UI elements, layout or product requirements, "
                    "important states, and ambiguities. Also classify the image's semantic role "
                    "(logo, mascot, hero illustration, photo, background, icon, or screenshot), "
                    "dominant colors, background type, safest contain/cover behavior, useful "
                    "screen placement, placement rationale, and safe padding around the subject. "
                    "Be faithful to visible evidence; do not invent requirements."
                ),
                schema=ImageAttachmentAnalysis,
                image_bytes=raw,
                image_mime_type=mime_type,
            )
            markdown = [
                "# Attached image context",
                f"- File: `{safe_name}`",
                f"- Summary: {analysis.summary}",
                "",
                "## Visible text",
                *[f"- {item}" for item in analysis.visible_text],
                "",
                "## UI elements",
                *[f"- {item}" for item in analysis.ui_elements],
                "",
                "## Requirements and states",
                *[f"- {item}" for item in analysis.requirements_and_states],
                "",
                "## Asset placement guidance",
                f"- Role: {analysis.visual_role}",
                f"- Dominant colors: {', '.join(analysis.dominant_colors) or 'unknown'}",
                f"- Background: {analysis.background_type}",
                f"- Fit: {analysis.recommended_fit}",
                f"- Placement: {analysis.recommended_placement}",
                f"- Reason: {analysis.placement_reason or 'Use screen hierarchy and current layout.'}",
                f"- Safe padding: {analysis.safe_padding_percent}%",
            ]
            size = _image_size(raw)
            width, height = size or (None, None)
            return AttachmentParseResult(
                name=safe_name,
                kind="image",
                markdown="\n".join(markdown).strip(),
                asset=ExactAsset(
                    id=asset_id,
                    name=safe_name,
                    mime_type=mime_type,
                    width=width,
                    height=height,
                    aspect_ratio=(round(width / height, 6) if width and height else None),
                    visual_role=analysis.visual_role,
                    dominant_colors=analysis.dominant_colors,
                    background_type=analysis.background_type,
                    recommended_fit=("cover" if analysis.recommended_fit.casefold() == "cover" else "contain"),
                    recommended_placement=analysis.recommended_placement,
                    placement_reason=analysis.placement_reason,
                    safe_padding_percent=analysis.safe_padding_percent,
                ),
            )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AppError(
            "ATTACHMENT_PARSE_FAILED",
            "Attachment could not be parsed",
            str(error),
            422,
        ) from error
    raise AppError(
        "ATTACHMENT_TYPE_UNSUPPORTED",
        "Unsupported attachment type",
        "Supported: PNG, JPG, SVG, WEBP, TXT, Markdown, JSON, CSV, YAML, BPMN.",
        415,
    )


@router.post("/sessions", response_model=SessionView, status_code=status.HTTP_201_CREATED)
async def create_session(request: Request, body: SessionCreate) -> SessionView:
    llm = getattr(request.app.state, "llm", None)
    if llm is not None:
        asyncio.create_task(llm.prewarm())
    return await request.app.state.store.create_session(body.title.strip() or "Untitled session")


@router.get("/sessions", response_model=list[SessionView])
async def list_sessions(request: Request) -> list[SessionView]:
    return await request.app.state.store.list_sessions()


@router.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: UUID) -> dict[str, str]:
    await request.app.state.runs.delete_session(session_id)
    return {"status": "deleted"}


@router.get("/sessions/{session_id}/runs", response_model=list[RunView])
async def list_runs(request: Request, session_id: UUID) -> list[RunView]:
    if not await request.app.state.store.get_session(session_id):
        raise not_found("Session")
    return await request.app.state.store.list_runs(session_id)


@router.put("/sessions/{session_id}/workspace", response_model=SessionView)
async def update_session_workspace(
    request: Request, session_id: UUID, body: SessionWorkspaceUpdate
) -> SessionView:
    if not await request.app.state.store.get_session(session_id):
        raise not_found("Session")
    return await request.app.state.store.update_session_workspace(session_id, body)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=RunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_message(
    request: Request, session_id: UUID, body: MessageCreate
) -> RunView:
    if not await request.app.state.store.get_session(session_id):
        raise not_found("Session")
    run = await request.app.state.store.create_run(
        session_id,
        RunCreate(
            prompt=body.content,
            screen_name=body.screen_name_hint or "Screen",
            platform=body.platform_hint,
            style_name=body.style_hint,
            library_ids=body.library_ids,
            mcp_profile=body.mcp_profile,
            assets=body.assets,
        ),
    )
    await request.app.state.events.emit(
        run.id,
        run.revision,
        "run.created",
        {"stage": run.stage, "message": "Message accepted"},
    )
    request.app.state.runs.start(run.id)
    return run


@router.post(
    "/sessions/{session_id}/runs",
    response_model=RunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(request: Request, session_id: UUID, body: RunCreate) -> RunView:
    if not await request.app.state.store.get_session(session_id):
        raise not_found("Session")
    run = await request.app.state.store.create_run(session_id, body)
    await request.app.state.events.emit(
        run.id,
        run.revision,
        "run.created",
        {"stage": run.stage, "message": "Request accepted"},
    )
    request.app.state.runs.start(run.id)
    return run


@router.get("/runs/{run_id}", response_model=RunView)
async def get_run(request: Request, run_id: UUID) -> RunView:
    run = await request.app.state.store.get_run(run_id)
    if run is None:
        raise not_found("Run")
    return run


@router.get("/runs/{run_id}/artifacts", response_model=RunArtifacts)
async def get_run_artifacts(request: Request, run_id: UUID) -> RunArtifacts:
    run = await request.app.state.store.get_run(run_id)
    if run is None:
        raise not_found("Run")
    values = await request.app.state.store.list_artifacts(run.id, run.revision)
    return RunArtifacts.model_validate(values)


@router.get("/runs/{run_id}/preview")
async def get_run_preview(
    request: Request,
    run_id: UUID,
    mode: str = "desktop",
    screen: str | None = None,
) -> Response:
    previews_dir = Path(__file__).resolve().parent.parent / "data" / "previews"
    if screen:
        clean_screen = "".join(
            character for character in screen if character.isalnum() or character in "_-"
        )
        for target in previews_dir.glob(f"{run_id}_{clean_screen}.*"):
            ext = target.suffix.lower().lstrip(".")
            media_type = "image/svg+xml" if ext == "svg" else f"image/{ext}"
            return Response(content=target.read_bytes(), media_type=media_type)
    clean_mode = "mobile" if mode == "mobile" else "desktop"

    for ext, media_type in [
        ("jpg", "image/jpeg"),
        ("png", "image/png"),
        ("svg", "image/svg+xml"),
    ]:
        target = previews_dir / f"{run_id}_{clean_mode}.{ext}"
        if target.is_file():
            return Response(
                content=target.read_bytes(),
                media_type=media_type,
                headers={"Cache-Control": "public, max-age=3600"},
            )

    candidates = list(previews_dir.glob(f"{run_id}*.*"))
    if candidates:
        target_file = candidates[0]
        ext = target_file.suffix.lower().lstrip(".")
        media_type = "image/svg+xml" if ext == "svg" else f"image/{ext}"
        return Response(
            content=target_file.read_bytes(),
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    raise not_found("Preview image")


@router.get("/runs/{run_id}/events")
async def stream_events(
    request: Request,
    run_id: UUID,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    if not await request.app.state.store.get_run(run_id):
        raise not_found("Run")
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    return StreamingResponse(
        request.app.state.events.subscribe(run_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/reviews", status_code=status.HTTP_202_ACCEPTED)
async def review_run(request: Request, run_id: UUID, body: ReviewCreate) -> dict[str, str]:
    await request.app.state.runs.review(run_id, body)
    return {"status": "accepted"}


@router.post("/runs/{run_id}/layout/recheck")
async def recheck_layout(request: Request, run_id: UUID) -> dict[str, Any]:
    layout = await request.app.state.runs.recheck_layout(run_id)
    return {"status": "rechecked", "layout_review": layout}


@router.post("/runs/{run_id}/canvas/sync")
async def sync_canvas(request: Request, run_id: UUID) -> dict[str, Any]:
    sync = await request.app.state.runs.sync_canvas(run_id)
    return {"status": "synced", "canvas_sync": sync}


@router.get("/runs/{run_id}/download")
async def download_run_file(request: Request, run_id: UUID) -> Response:
    run = await request.app.state.store.get_run(run_id)
    if run is None:
        raise not_found("Run")
    if not run.mcp_profile:
        raise AppError(
            "MCP_CONTEXT_REQUIRED",
            "OpenPencil context is required",
            "Configure OpenPencil before downloading.",
            409,
        )
    layout = await request.app.state.runs.recheck_layout(run_id)
    if layout.get("status") != "valid":
        raise AppError(
            "EXPORT_PREFLIGHT_FAILED",
            "Export is blocked by layout findings",
            layout.get("summary", "Fix the layout findings before downloading."),
            409,
            action="Request changes or edit the live OpenPencil canvas, then recheck.",
        )
    await request.app.state.store.set_artifact(
        run.id,
        run.revision,
        "export_preflight",
        {"status": "passed", "source": "live_openpencil", "layout_status": layout.get("status")},
    )
    artifact = await request.app.state.store.get_artifact(run.id, run.revision, "openpencil_artifact") or {}
    path = str(artifact.get("output_file") or run.mcp_profile.output_file or "")
    if not path:
        raise AppError(
            "OUTPUT_FILE_MISSING",
            "Output file is missing",
            "Build the design before downloading.",
            409,
        )
    raw, media_type = await request.app.state.openpencil.download_workspace_file(
        run.mcp_profile.endpoint,
        path,
    )
    filename = path.replace("\\", "/").rsplit("/", 1)[-1] or "design.fig"
    return Response(
        content=raw,
        media_type=media_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_run(
    request: Request,
    run_id: UUID,
    body: RunRetry | None = None,
) -> dict[str, str]:
    await request.app.state.runs.retry(run_id, body.mcp_profile if body else None)
    return {"status": "accepted"}


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(request: Request, run_id: UUID) -> dict[str, str]:
    await request.app.state.runs.cancel(run_id)
    return {"status": "accepted"}


@router.post("/integrations/openpencil/probe", response_model=OpenPencilCapability)
async def probe_mcp(request: Request, body: McpProbeRequest) -> OpenPencilCapability:
    return await request.app.state.openpencil.probe(str(body.endpoint))


@router.post(
    "/integrations/openpencil/documents",
    response_model=list[OpenPencilDocumentView],
)
async def openpencil_documents(
    request: Request, body: McpProbeRequest
) -> list[OpenPencilDocumentView]:
    return await request.app.state.openpencil.documents(str(body.endpoint))


@router.post(
    "/integrations/openpencil/documents/create",
    response_model=OpenPencilDocumentView,
    status_code=status.HTTP_201_CREATED,
)
async def create_openpencil_document(
    request: Request, body: NamedMcpRequest
) -> OpenPencilDocumentView:
    return await request.app.state.openpencil.create_document(
        str(body.endpoint), body.name
    )


@router.post(
    "/integrations/openpencil/documents/{document_id}/pages",
    response_model=OpenPencilDocumentView,
    status_code=status.HTTP_201_CREATED,
)
async def create_openpencil_page(
    request: Request, document_id: str, body: NamedMcpRequest
) -> OpenPencilDocumentView:
    return await request.app.state.openpencil.create_page(
        str(body.endpoint), document_id, body.name
    )


@router.post("/integrations/openpencil/components")
async def openpencil_components(
    request: Request,
    profile: OpenPencilProfile,
) -> list[dict[str, object]]:
    components = await request.app.state.openpencil.components(profile)
    return [component.model_dump(mode="json") for component in components]


@router.get("/design-systems", response_model=list[DesignSystemView])
async def list_design_systems(request: Request) -> list[DesignSystemView]:
    settings = request.app.state.settings
    folder = settings.design_data_dir / "design-systems"
    results: list[DesignSystemView] = []
    if not folder.is_dir():
        return results

    for fig in sorted(folder.glob("*.fig")):
        stem = fig.stem.lower()
        if "taptap" in stem or "tap tap" in stem:
            sys_id = "taptap"
            name = "TapTap Design System"
            knowledge_id = "taptap"
        elif "shadcn" in stem:
            sys_id = "shadcn-ui"
            name = "shadcn/ui Design System"
            knowledge_id = "shadcn-ui"
        elif "material 3" in stem or "material-3" in stem or "material_3" in stem:
            sys_id = "material-3"
            name = "Material 3 (Google)"
            knowledge_id = "auto"
        elif "material" in stem:
            sys_id = "material-ui"
            name = "Material UI (MUI)"
            knowledge_id = "auto"
        elif "v0.3" in stem or "v0" in stem:
            sys_id = "design-system-v0.3"
            name = "Design System v0.3"
            knowledge_id = "auto"
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "custom"
            sys_id = f"custom-{slug}"
            name = fig.stem
            knowledge_id = "auto"

        results.append(
            DesignSystemView(
                id=sys_id,
                name=name,
                path=str(fig.resolve()),
                knowledge_id=knowledge_id,
            )
        )
    return results
