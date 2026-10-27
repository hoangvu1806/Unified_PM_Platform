"""User-provided images in screens: the HTML references ``asset:<id>``; documents get data URLs."""

from __future__ import annotations

import asyncio
import base64
import re


ASSET_REF = re.compile(r"asset:([a-z0-9][a-z0-9-]{2,79})")
MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "svg": "image/svg+xml"}


def _data_url(project_id: str | None, asset_id: str) -> str | None:
    from ..storage.assets import read_asset  # storage settings; imported lazily

    try:
        data = read_asset(project_id, asset_id)
    except Exception:  # noqa: BLE001 — a missing asset renders as a broken image (lint reports it)
        return None
    if data is None:
        return None
    kind = next((m for ext, m in MIME.items() if f"-{ext}-" in asset_id), "image/png")
    return f"data:{kind};base64,{base64.b64encode(data).decode('ascii')}"


async def inline_assets(html: str, project_id: str | None) -> str:
    ids = sorted(set(ASSET_REF.findall(html)))
    if not ids:
        return html
    found = await asyncio.gather(*(asyncio.to_thread(_data_url, project_id, i) for i in ids))
    urls = dict(zip(ids, found))
    return ASSET_REF.sub(lambda m: urls.get(m.group(1)) or m.group(0), html)
