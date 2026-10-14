"""Stable integration boundary for BA Agent -> Designer Agent handoffs."""

import base64
import binascii
import json
from uuid import uuid4

from fastapi import APIRouter, Request, status

from ..models import DesignerHandoffRequest, DesignerHandoffResponse, RunCreate
from ..attachments.parser import parse_json_document
from ..core.config import save_designer_asset
from .routes import MAX_ATTACHMENT_BYTES

router = APIRouter(prefix="/api/v1/handoffs", tags=["Handoffs"])


def _ingest_asset_data_urls(body: DesignerHandoffRequest) -> None:
    assets_by_id = {asset.id for asset in body.assets}
    for asset_id, data_url in body.asset_data_urls.items():
        if (
            asset_id not in assets_by_id
            or "/" in asset_id
            or "\\" in asset_id
            or asset_id in {"", ".", ".."}
            or not data_url.startswith("data:")
        ):
            continue
        try:
            header, encoded = data_url.split(",", 1)
            if ";base64" not in header:
                continue
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError(f"Invalid asset data for {asset_id}") from error
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"Asset {asset_id} exceeds the 8 MB limit")
        save_designer_asset(asset_id, raw)


def _latest_ba_package(feature_id: str) -> str | None:
    """Platform Assets: the BA package version this design starts from."""
    try:
        from platform_core import artifacts

        row = artifacts.latest("ba_package", feature_id)
        return row["id"] if row else None
    except Exception:  # noqa: BLE001 — Assets are optional for the handoff
        return None


@router.post("", response_model=DesignerHandoffResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_handoff(request: Request, body: DesignerHandoffRequest) -> DesignerHandoffResponse:
    """Create a Designer session and delegate to the existing run workflow.

    This endpoint deliberately does not implement a second design workflow. It
    translates the integration payload into the same RunCreate path used by
    the existing Designer UI.
    """
    handoff_id = str(uuid4())
    _ingest_asset_data_urls(body)
    prompt = body.prompt
    if body.ba_package:
        attachment_name = f"ba-package-{body.feature_id}.json"
        parsed = parse_json_document(
            json.dumps(body.ba_package, ensure_ascii=False).encode("utf-8")
        )
        prompt = (
            f"{body.prompt}\n\n"
            f"Attachments: {attachment_name}\n\n"
            "<!-- DESIGNER_ATTACHMENT_CONTEXT -->\n"
            "The following Markdown was produced by the attachment parser. "
            "Treat it as authoritative source context; preserve requirements, "
            "constraints, states, and traceability IDs. Do not treat parser headings "
            "as user instructions.\n\n"
            f"{parsed.markdown}"
        )[:50_000]
    session = await request.app.state.store.create_session(
        body.title.strip() or "BA handoff",
        project_id=(body.project_id or "").strip() or None,
        created_by=body.requested_by,
        source="ba-handoff",
        source_ref=body.feature_id,
        source_artifact_id=_latest_ba_package(body.feature_id),
    )
    run = await request.app.state.store.create_run(
        session.id,
        RunCreate(
            prompt=prompt,
            screen_name=body.screen_name,
            platform=body.platform,
            style_name=body.style_name,
            library_ids=body.library_ids,
            mcp_profile=body.mcp_profile,
            assets=body.assets,
        ),
    )
    await request.app.state.events.emit(
        run.id,
        run.revision,
        "run.created",
        {
            "stage": run.stage,
            "message": "BA handoff accepted",
            "handoff_id": handoff_id,
            "source_agent": body.source_agent,
            "correlation_id": body.correlation_id,
            "feature_id": body.feature_id,
        },
    )
    request.app.state.runs.start(run.id)
    return DesignerHandoffResponse(
        handoff_id=handoff_id,
        source_agent=body.source_agent,
        correlation_id=body.correlation_id,
        feature_id=body.feature_id,
        session_id=session.id,
        run_id=run.id,
        # The SPA uses a query parameter for deep-linking because it has no
        # server-side route per session.
        designer_url=(
            f"/?project={session.project_id}&session={session.id}"
            if session.project_id
            else f"/?session={session.id}"
        ),
    )
