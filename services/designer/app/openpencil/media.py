import base64
import json
import re
import struct
import unicodedata
from pathlib import Path
from typing import Any

from mcp import ClientSession

from ..core.config import designer_asset_dir, designer_asset_file
from ..core.errors import AppError
from ..models import UiNode, UiSpecification


def _walk_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    result = [node]
    for child in node.get("children", []) or []:
        if isinstance(child, dict):
            result.extend(_walk_nodes(child))
    return result


def _raster_size(path: Path) -> tuple[int, int] | None:
    """Read PNG/JPEG dimensions without adding an image-processing dependency."""
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 < len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(data):
                break
            length = int.from_bytes(data[offset : offset + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if offset + 7 <= len(data):
                    height = int.from_bytes(data[offset + 3 : offset + 5], "big")
                    width = int.from_bytes(data[offset + 5 : offset + 7], "big")
                    return width, height
                break
            if length < 2:
                break
            offset += length
    return None


def _contained_size(
    source: tuple[int, int], box_width: float, box_height: float
) -> tuple[float, float]:
    """Fit an image inside a box without distortion or source upscaling."""
    source_width, source_height = source
    scale = min(
        box_width / source_width,
        box_height / source_height,
        1.0,
    )
    return round(source_width * scale, 2), round(source_height * scale, 2)


def _image_target(instance: dict[str, Any], asset_id: str) -> dict[str, Any] | None:
    """Find the leaf image shape inside a mounted branded component."""
    nodes = _walk_nodes(instance)
    token = f"asset::{asset_id}".casefold()
    named = [
        node
        for node in nodes
        if token in str(node.get("name", "")).casefold()
        and node.get("type") in {"RECTANGLE", "ELLIPSE"}
    ]
    if named:
        return named[0]
    preferred_names = ("mascot image", "logo image", "image", "asset")
    for preferred in preferred_names:
        for node in nodes:
            if (
                preferred in str(node.get("name", "")).casefold()
                and node.get("type") in {"RECTANGLE", "ELLIPSE"}
            ):
                return node
    shapes = [node for node in nodes if node.get("type") in {"RECTANGLE", "ELLIPSE"}]
    return shapes[-1] if shapes else None


async def apply_uploaded_component_media(
    client: Any,
    session: ClientSession,
    *,
    document_id: str,
    page_id: str,
    bindings: Any,
    instance_ids: dict[str, str],
    exact_assets: list[dict[str, Any]],
    asset_node_ids: dict[str, str] | None = None,
    component_media: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Attach uploaded bytes to the image leaf of mounted asset components.

    Rendering JSX can preserve the component structure but not arbitrary embedded
    image bytes. OpenPencil's set_image_fill is therefore called after mounting,
    using the original uploaded file from the backend asset store.
    """
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    if not exact_assets and not component_media:
        return {"applied": 0, "failed": 0, "assets": []}

    asset_by_id = {
        str(item.get("id")): item
        for item in exact_assets
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    asset_root = designer_asset_dir()
    target = {"document_id": document_id, "page_id": page_id}
    component_asset_ids = asset_node_ids or {}
    for binding in getattr(bindings, "bindings", []):
        node_id = str(getattr(binding, "node_id", ""))
        if node_id not in component_asset_ids:
            continue
        instance_id = str(instance_ids.get(node_id) or "")
        if not instance_id:
            failed.append({"binding": getattr(binding, "node_id", ""), "error": "instance missing"})
            continue
        requested_id = str(component_asset_ids.get(node_id) or "")
        asset = asset_by_id.get(requested_id) if requested_id else None
        if asset is None and len(asset_by_id) == 1:
            asset = next(iter(asset_by_id.values()))
        if asset is None and len(asset_by_id) > 1:
            failed.append(
                {
                    "binding": getattr(binding, "node_id", ""),
                    "error": "asset selection is ambiguous",
                    "available_assets": sorted(asset_by_id),
                }
            )
            continue
        asset_id = str((asset or {}).get("id") or "")
        asset_file = designer_asset_file(asset_id) if asset_id else None
        if not asset_file or not asset_file.is_file():
            source_path = (component_media or {}).get(str(getattr(binding, "component_id", "")), "")
            asset_file = Path(source_path) if source_path else None
            asset_id = requested_id or "design-system-component"
        if not asset_id or not asset_file or not asset_file.is_file():
            failed.append({"binding": getattr(binding, "node_id", ""), "error": "asset bytes missing"})
            continue
        try:
            instance = await client._call(session, "get_node", {**target, "id": instance_id, "depth": 8})
            image_node = _image_target(instance, asset_id)
            if not image_node or not image_node.get("id"):
                raise ValueError("image leaf not found inside mounted component")
            encoded = base64.b64encode(asset_file.read_bytes()).decode("ascii")
            result = await client._call(
                session,
                "set_image_fill",
                {
                    **target,
                    "id": str(image_node["id"]),
                    "image_data": encoded,
                    "scale_mode": "FIT",
                },
            )
            verification = await client._call(
                session,
                "get_node",
                {**target, "id": str(image_node["id"]), "depth": 0},
            )
            fills = verification.get("fills") or []
            if not any(str(fill.get("type", "")).upper() == "IMAGE" for fill in fills if isinstance(fill, dict)):
                raise ValueError("OpenPencil did not expose an IMAGE fill after import")
            applied.append(
                {
                    "asset_id": asset_id,
                    "instance_id": instance_id,
                    "target_node_id": str(image_node["id"]),
                    "image_hash": result.get("imageHash", ""),
                }
            )
        except Exception as error:
            failed.append({"binding": getattr(binding, "node_id", ""), "error": str(error)})
    return {"applied": len(applied), "failed": len(failed), "assets": applied, "errors": failed}


async def apply_uploaded_asset_markers(
    client: Any,
    session: ClientSession,
    *,
    document_id: str,
    page_id: str,
    exact_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply original bytes to rendered nodes named ``asset::<id>``."""
    asset_root = designer_asset_dir()
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    target = {"document_id": document_id, "page_id": page_id}
    for item in exact_assets:
        asset_id = str(item.get("id") or "") if isinstance(item, dict) else ""
        if not asset_id:
            continue
        asset_file = designer_asset_file(asset_id)
        if not asset_file.is_file():
            failed.append({"asset_id": asset_id, "error": "asset bytes missing"})
            continue
        matches = await client._call(session, "find_nodes", {**target, "name": f"asset::{asset_id}"})
        nodes = matches.get("nodes", []) if isinstance(matches, dict) else []
        if not nodes:
            # A design-system component may have consumed the same asset via
            # apply_uploaded_component_media; absence of a direct marker is
            # not an error in that path.
            continue
        encoded = base64.b64encode(asset_file.read_bytes()).decode("ascii")
        applied_count = 0
        for match in nodes:
            node_id = str(match.get("id") or "")
            if not node_id:
                continue
            node = await client._call(
                session, "get_node", {**target, "id": node_id, "depth": 0}
            )
            source_size = _raster_size(asset_file)
            box_width = float(node.get("width", node.get("w", 0)) or 0)
            box_height = float(node.get("height", node.get("h", 0)) or 0)
            fitted_size: tuple[float, float] | None = None
            if source_size and box_width > 0 and box_height > 0:
                fitted_size = _contained_size(source_size, box_width, box_height)
                await client._call(
                    session,
                    "node_resize",
                    {
                        **target,
                        "id": node_id,
                        "width": fitted_size[0],
                        "height": fitted_size[1],
                    },
                )
            await client._call(
                session,
                "set_image_fill",
                {**target, "id": node_id, "image_data": encoded, "scale_mode": "FIT"},
            )
            verification = await client._call(session, "get_node", {**target, "id": node_id, "depth": 0})
            fills = verification.get("fills", []) if isinstance(verification, dict) else []
            if any(str(fill.get("type", "")).upper() == "IMAGE" for fill in fills if isinstance(fill, dict)):
                applied.append(
                    {
                        "asset_id": asset_id,
                        "node_id": node_id,
                        "source_size": list(source_size) if source_size else None,
                        "display_size": list(fitted_size) if fitted_size else None,
                        "scale_mode": "FIT",
                    }
                )
                applied_count += 1
        if not applied_count:
            failed.append({"asset_id": asset_id, "error": "OpenPencil did not expose an IMAGE fill"})
    return {"applied": len(applied), "failed": len(failed), "assets": applied, "errors": failed}


async def apply_unsplash_media(
    client: Any,
    session: ClientSession,
    *,
    document_id: str,
    page_id: str,
    specification: UiSpecification,
) -> dict[str, Any]:
    # Only explicitly requested stock media may leave the local canvas. User
    # assets and placeholders are handled by the local asset/render pipeline
    # and must never trigger a provider lookup.
    media = _stock_media_nodes(specification.root)
    if not media:
        return {"provider": "none", "applied": 0, "failed": 0, "assets": []}

    requests: list[dict[str, Any]] = []
    missing: list[str] = []
    for index, node in enumerate(media):
        matches = await client._call(
            session,
            "find_nodes",
            {
                "name": f"photo::{node.id}",
                "document_id": document_id,
                "page_id": page_id,
            },
        )
        nodes = matches.get("nodes", [])
        if not nodes:
            missing.append(node.id)
            continue
        target = nodes[0]
        width = float(target.get("width", target.get("w", 800)))
        height = float(target.get("height", target.get("h", 600)))
        orientation = (
            "square"
            if abs(width - height) < 60
            else "portrait"
            if height > width
            else "landscape"
        )
        requests.append(
            {
                "id": str(target["id"]),
                "query": _english_query(specification, node),
                "orientation": orientation,
                "index": index % 6,
            }
        )
    if missing:
        raise AppError(
            "OPENPENCIL_MEDIA_TARGET_MISSING",
            "Media placeholders are missing",
            f"Missing photo markers: {', '.join(missing)}",
            409,
            retryable=True,
            action="Regenerate the affected section with every photo::<id> marker.",
        )

    result = await client._call(
        session,
        "stock_photo",
        {
            "requests": json.dumps(requests),
            "document_id": document_id,
            "page_id": page_id,
        },
    )
    provider = str(result.get("provider", "")).lower()
    if provider != "unsplash":
        raise AppError(
            "OPENPENCIL_UNSPLASH_REQUIRED",
            "OpenPencil must use Unsplash",
            f"Active stock-photo provider: {provider or 'none'}.",
            409,
            retryable=True,
            action="Configure an Unsplash key and select Unsplash in OpenPencil AI settings.",
        )
    request_by_id = {item["id"]: item for item in requests}
    assets: list[dict[str, Any]] = []
    for item in result.get("results", []):
        photo = item.get("photo") or {}
        node_id = str(item.get("id", ""))
        request = request_by_id.get(node_id, {})
        if not photo:
            continue
        source_id = str(photo.get("sourceId", ""))
        assets.append(
            {
                "target_node_id": node_id,
                "query": request.get("query", ""),
                "orientation": request.get("orientation", "landscape"),
                "index": request.get("index", 0),
                "provider": provider,
                "source_id": source_id,
                "photographer": photo.get("photographer", ""),
                "width": photo.get("width"),
                "height": photo.get("height"),
                "source_url": f"https://unsplash.com/photos/{source_id}" if source_id else "",
                "attribution": f"Photo by {photo.get('photographer', '')} on Unsplash",
                "download_tracking": "handled by the OpenPencil Unsplash provider",
            }
        )
    return {
        "provider": provider,
        "applied": int(result.get("applied", len(assets))),
        "failed": int(result.get("failed", len(requests) - len(assets))),
        "assets": assets,
    }


def is_stock_media(node: UiNode) -> bool:
    """Return whether a media node explicitly requests a stock photo.

    The old behavior treated every ``kind=media`` node as a stock photo. That
    made user-provided mascots, local assets and CSS placeholders call the
    external provider path. Keep the default local and require an explicit
    source/provider marker for network-backed media.
    """
    if node.kind != "media":
        return False
    content = node.content or {}
    source = str(
        content.get("source")
        or content.get("source_type")
        or content.get("asset_source")
        or content.get("provider")
        or ""
    ).strip().lower()
    if source in {"stock", "stock_photo", "stock-photo", "unsplash", "pexels"}:
        return True
    return bool(content.get("use_stock") is True or content.get("stock") is True)


def _stock_media_nodes(root: UiNode) -> list[UiNode]:
    result: list[UiNode] = []

    def collect(node: UiNode) -> None:
        if is_stock_media(node):
            result.append(node)
        for child in node.children:
            collect(child)

    collect(root)
    return result


def _english_query(specification: UiSpecification, node: UiNode) -> str:
    value = str(
        node.content.get("query")
        or node.content.get("alt")
        or node.content.get("description")
        or node.name
    )
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    clean = re.sub(r"[^a-zA-Z0-9 ]+", " ", ascii_value)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean.split()) < 2:
        clean = f"{specification.screen_name} authentic editorial photography"
    return clean[:120]
