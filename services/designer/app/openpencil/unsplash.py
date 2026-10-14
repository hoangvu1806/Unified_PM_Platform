import asyncio
import base64
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("designer_agent.unsplash")

# In-memory cache to avoid duplicate API requests across desktop/mobile views
_PHOTO_CACHE: dict[str, "UnsplashPhotoResult"] = {}


@dataclass(frozen=True)
class UnsplashPhotoResult:
    base64_data: str
    photographer: str
    photo_id: str
    photo_url: str


class UnsplashService:
    def __init__(self, access_key: str) -> None:
        self.access_key = access_key.strip()

    @property
    def is_available(self) -> bool:
        return bool(self.access_key)

    async def search_and_download(
        self,
        query: str,
        orientation: str = "landscape",
        target_dim: int = 1080,
    ) -> UnsplashPhotoResult | None:
        if not self.is_available:
            return None

        clean_q = re.sub(r"[\W_]+", " ", query).strip()
        if not clean_q:
            clean_q = "modern product workspace"

        cache_key = f"{clean_q.lower()}_{orientation}_{target_dim}"
        if cache_key in _PHOTO_CACHE:
            logger.info("Unsplash cache hit for query: '%s'", clean_q)
            return _PHOTO_CACHE[cache_key]

        headers = {
            "Authorization": f"Client-ID {self.access_key}",
            "Accept-Version": "v1",
        }
        orient_param = "squarish" if orientation == "square" else orientation
        params: dict[str, Any] = {
            "query": clean_q,
            "per_page": 1,
            "orientation": orient_param,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://api.unsplash.com/search/photos",
                    headers=headers,
                    params=params,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Unsplash API returned %d: %s for query '%s'",
                        resp.status_code,
                        resp.text[:200],
                        clean_q,
                    )
                    return None

                data = resp.json()
                results = data.get("results", [])
                if not results:
                    logger.info("No Unsplash photos found for query: '%s'", clean_q)
                    return None

                photo = results[0]
                urls = photo.get("urls", {})
                if target_dim <= 400:
                    img_url = urls.get("small") or urls.get("regular")
                else:
                    img_url = urls.get("regular") or urls.get("full") or urls.get("small")

                if not img_url:
                    return None

                img_resp = await client.get(img_url)
                if img_resp.status_code != 200:
                    logger.warning("Failed to download Unsplash image: %d", img_resp.status_code)
                    return None

                b64_data = base64.b64encode(img_resp.content).decode("ascii")
                result = UnsplashPhotoResult(
                    base64_data=b64_data,
                    photographer=photo.get("user", {}).get("name", "Unsplash Contributor"),
                    photo_id=photo.get("id", ""),
                    photo_url=img_url,
                )
                _PHOTO_CACHE[cache_key] = result
                logger.info("Fetched Unsplash photo for '%s' by %s", clean_q, result.photographer)
                return result
        except Exception as err:
            logger.warning("Exception fetching Unsplash photo for '%s': %s", clean_q, err)
            return None


async def batch_fetch_photos(
    queries: list[dict[str, Any]],
    access_key: str,
) -> dict[str, UnsplashPhotoResult]:
    """
    Fetch multiple Unsplash photos concurrently.
    queries: list of dicts with {"node_id": str, "query": str, "orientation": str, "dim": int}
    Returns mapping of node_id -> UnsplashPhotoResult.
    """
    service = UnsplashService(access_key)
    if not service.is_available:
        return {}

    async def _fetch_one(item: dict[str, Any]) -> tuple[str, UnsplashPhotoResult | None]:
        res = await service.search_and_download(
            query=item["query"],
            orientation=item.get("orientation", "landscape"),
            target_dim=item.get("dim", 1080),
        )
        return item["node_id"], res

    tasks = [_fetch_one(q) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out: dict[str, UnsplashPhotoResult] = {}
    for r in results:
        if isinstance(r, tuple) and r[1] is not None:
            out[r[0]] = r[1]
    return out

