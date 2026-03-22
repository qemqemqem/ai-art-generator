"""
Image Search Providers.

Abstract interface for searching the web for images, plus concrete
implementations.

Providers:
  - SerpAPI (default) -- wraps Google Images via serpapi.com
  - Google CSE        -- Google Custom Search JSON API (requires CSE setup)

To add a new provider, subclass ImageSearchProvider and implement search().
"""

import io
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

SERPAPI_ENDPOINT = "https://serpapi.com/search"
GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"

_SERPAPI_ASPECT_RATIO_MAP = {
    "square": "s",
    "landscape": "w",
    "portrait": "t",
}

_SERPAPI_SAFE_SEARCH_MAP = {
    "off": "off",
    "moderate": "active",
    "strict": "active",
}

_GOOGLE_CSE_ASPECT_RATIO_MAP = {
    "square": "square",
    "landscape": "wide",
    "portrait": "tall",
}

_GOOGLE_CSE_SAFE_SEARCH_MAP = {
    "off": "off",
    "moderate": "medium",
    "strict": "high",
}


@dataclass
class ImageSearchResult:
    """A single image result from a search."""
    url: str
    width: int
    height: int
    title: str
    source_url: str


class ImageSearchProvider(ABC):
    """Abstract base for image search providers."""

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        count: int = 1,
        aspect_ratio: str | None = None,
        image_type: str | None = None,
        safe_search: str = "moderate",
    ) -> list[ImageSearchResult]:
        """
        Search for images matching a query.

        Args:
            query: Search query string.
            count: Number of results to return (1-10).
            aspect_ratio: "square", "landscape", or "portrait".
            image_type: "photo", "clipart", "lineart", or "face".
            safe_search: "off", "moderate", or "strict".

        Returns:
            List of ImageSearchResult with URLs and metadata.
        """
        ...


# ---------------------------------------------------------------------------
# SerpAPI  (default)
# ---------------------------------------------------------------------------

class SerpAPISearchProvider(ImageSearchProvider):
    """Google Images search via SerpAPI (serpapi.com)."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("SERPAPI_API_KEY")

    async def search(
        self,
        query: str,
        *,
        count: int = 1,
        aspect_ratio: str | None = None,
        image_type: str | None = None,
        safe_search: str = "moderate",
    ) -> list[ImageSearchResult]:
        if not self.api_key:
            raise RuntimeError(
                "SerpAPI key not set. "
                "Get one at https://serpapi.com/ then set SERPAPI_API_KEY."
            )

        params: dict[str, str | int] = {
            "api_key": self.api_key,
            "engine": "google_images",
            "q": query,
            "ijn": 0,
        }

        if aspect_ratio and aspect_ratio in _SERPAPI_ASPECT_RATIO_MAP:
            params["imgar"] = _SERPAPI_ASPECT_RATIO_MAP[aspect_ratio]

        if image_type:
            params["image_type"] = image_type

        safe_val = _SERPAPI_SAFE_SEARCH_MAP.get(safe_search)
        if safe_val:
            params["safe"] = safe_val

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(SERPAPI_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()

        items = data.get("images_results", [])
        if not items:
            return []

        results = []
        for item in items:
            if len(results) >= count:
                break
            url = item.get("original", "")
            if not url or not url.startswith(("http://", "https://")):
                continue
            results.append(ImageSearchResult(
                url=url,
                width=item.get("original_width", 0),
                height=item.get("original_height", 0),
                title=item.get("title", ""),
                source_url=item.get("link", ""),
            ))

        return results


# ---------------------------------------------------------------------------
# Google Custom Search Engine  (alternative, requires CSE setup)
# ---------------------------------------------------------------------------

class GoogleCSESearchProvider(ImageSearchProvider):
    """Google Custom Search Engine image search."""

    def __init__(self, api_key: str | None = None, cse_id: str | None = None):
        self.api_key = api_key or os.environ.get("GOOGLE_CSE_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.cse_id = cse_id or os.environ.get("GOOGLE_CSE_ID")

    async def search(
        self,
        query: str,
        *,
        count: int = 1,
        aspect_ratio: str | None = None,
        image_type: str | None = None,
        safe_search: str = "moderate",
    ) -> list[ImageSearchResult]:
        if not self.api_key:
            raise RuntimeError(
                "Google CSE API key not set. "
                "Set GOOGLE_CSE_API_KEY or GOOGLE_API_KEY in your environment."
            )
        if not self.cse_id or self.cse_id.startswith("your_"):
            raise RuntimeError(
                "Google CSE ID not configured. "
                "Create a Programmable Search Engine at "
                "https://programmablesearchengine.google.com/controlpanel/create "
                "then set GOOGLE_CSE_ID in your environment."
            )

        params: dict[str, str | int] = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "searchType": "image",
            "num": min(count, 10),
            "safe": _GOOGLE_CSE_SAFE_SEARCH_MAP.get(safe_search, "medium"),
        }

        if aspect_ratio and aspect_ratio in _GOOGLE_CSE_ASPECT_RATIO_MAP:
            params["imgSize"] = _GOOGLE_CSE_ASPECT_RATIO_MAP[aspect_ratio]

        if image_type:
            params["imgType"] = image_type

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(GOOGLE_CSE_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()

        items = data.get("items", [])
        if not items:
            return []

        results = []
        for item in items:
            img_meta = item.get("image", {})
            results.append(ImageSearchResult(
                url=item["link"],
                width=img_meta.get("width", 0),
                height=img_meta.get("height", 0),
                title=item.get("title", ""),
                source_url=item.get("image", {}).get("contextLink", ""),
            ))

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def download_image(url: str, timeout: float = 30) -> Image.Image:
    """Download an image URL and return a PIL Image."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if content_type and not content_type.startswith("image/"):
        raise ValueError(
            f"URL returned non-image content-type: {content_type}"
        )

    return Image.open(io.BytesIO(resp.content))
