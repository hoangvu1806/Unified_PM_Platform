"""Project-matched local illustration assets for the style preview gallery."""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("designer_agent.preview_assets")
CATALOG_PATH = (Path(__file__).resolve().parents[2] / "assets" / "backgrounds" / "education"
                / "storyset" / "catalog.json")
ASSET_ROOT = CATALOG_PATH.parent


def catalog_assets() -> list[dict[str, Any]]:
    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        rows = payload.get("assets", [])
        return [row for row in rows if isinstance(row, dict) and row.get("id") and row.get("relative_path")]
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Preview illustration catalog unavailable: %s", error)
        return []


def relevant_assets(query: str) -> list[dict[str, Any]]:
    """Return only assets whose catalog tags match the project/screen context."""
    normalized = re.sub(r"[^\w\s-]", " ", query.casefold(), flags=re.UNICODE)
    words = set(normalized.split())
    matches = []
    for asset in catalog_assets():
        tags = [str(tag).casefold() for tag in asset.get("tags", [])]
        if any(tag in normalized or tag in words for tag in tags):
            path = ASSET_ROOT / str(asset["relative_path"])
            if path.is_file():
                matches.append({**asset, "path": path})
    return matches


def asset_by_id(asset_id: str, available: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    return next((asset for asset in (available if available is not None else catalog_assets())
                 if asset.get("id") == asset_id), None)


def inline_svg(asset: dict[str, Any]) -> str:
    """Encode a catalog SVG as a self-contained image URL for the sandboxed renderer."""
    path = asset.get("path") or (ASSET_ROOT / str(asset["relative_path"]))
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        logger.warning("Preview illustration %s could not be read: %s", asset.get("id"), error)
        return ""
    if b"<svg" not in raw[:1024]:
        logger.warning("Preview illustration %s is not SVG", asset.get("id"))
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")
