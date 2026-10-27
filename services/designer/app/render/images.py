"""Stock photo search for screens (no key needed): Unsplash when UNSPLASH_ACCESS_KEY is set,
otherwise Openverse (CC-licensed, mostly Flickr) and Wikimedia Commons in parallel.
Results are cached per query; a slow or failing source is skipped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("designer_agent.images")

USER_AGENT = "platform-designer/1.0 (internal UI design tool)"
TIMEOUT = 12
_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}


def _get(url: str, headers: dict[str, str] | None = None) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return json.load(response)


def _unsplash(query: str, orientation: str, key: str) -> list[dict[str, Any]]:
    params = {"query": query, "per_page": 8, "content_filter": "high"}
    if orientation in {"landscape", "portrait", "squarish"}:
        params["orientation"] = orientation
    data = _get("https://api.unsplash.com/search/photos?" + urllib.parse.urlencode(params),
                {"Authorization": f"Client-ID {key}"})
    return [{"url": r["urls"]["regular"], "width": r["width"], "height": r["height"],
             "title": r.get("alt_description") or "", "credit": f"{r['user']['name']} / Unsplash"}
            for r in data.get("results", [])]


def _openverse(query: str, orientation: str) -> list[dict[str, Any]]:
    params = {"q": query, "page_size": 8, "license_type": "commercial", "mature": "false"}
    ratio = {"landscape": "wide", "portrait": "tall", "squarish": "square"}.get(orientation)
    if ratio:
        params["aspect_ratio"] = ratio
    data = _get("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(params))
    return [{"url": r["url"], "width": r.get("width"), "height": r.get("height"), "title": r.get("title") or "",
             "credit": f"{r.get('creator') or 'unknown'} / {r.get('source')} ({r.get('license')})"}
            for r in data.get("results", []) if str(r.get("url", "")).startswith("https://")]


def _wikimedia(query: str, orientation: str) -> list[dict[str, Any]]:
    params = {"action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6,
              "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url|size", "iiurlwidth": 1280, "format": "json"}
    data = _get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params))
    out = []
    for page in (data.get("query") or {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        w, h = info.get("thumbwidth") or 0, info.get("thumbheight") or 0
        if not info.get("thumburl") or not w or not h:
            continue
        if orientation == "landscape" and w < h or orientation == "portrait" and h < w:
            continue
        out.append({"url": info["thumburl"], "width": w, "height": h,
                    "title": page.get("title", "").removeprefix("File:"), "credit": "Wikimedia Commons"})
    return out


async def find_images(query: str, orientation: str = "landscape", unsplash_key: str = "") -> list[dict[str, Any]]:
    cache_key = (query.strip().lower(), orientation)
    if cache_key in _cache:
        return _cache[cache_key]
    sources = [lambda: _unsplash(query, orientation, unsplash_key)] if unsplash_key else [
        lambda: _openverse(query, orientation), lambda: _wikimedia(query, orientation)]
    results = await asyncio.gather(*(asyncio.to_thread(s) for s in sources), return_exceptions=True)
    images: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Image search for %r failed: %s", query, result)
            continue
        images.extend(result)
    if images:
        _cache[cache_key] = images[:10]
    return images[:10]
