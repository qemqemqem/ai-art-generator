"""
Image Search Providers.

Abstract interface for searching the web for images, plus concrete
implementations. Currently supports Google Custom Search JSON API.

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

GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"

_ASPECT_RATIO_MAP = {
    "square": "square",
    "landscape": "wide",
    "portrait": "tall",
}

_SAFE_SEARCH_MAP = {
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
        if not self.cse_id:
            raise RuntimeError(
                "Google CSE ID not set. "
                "Set GOOGLE_CSE_ID in your environment."
            )

        params: dict[str, str | int] = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "searchType": "image",
            "num": min(count, 10),
            "safe": _SAFE_SEARCH_MAP.get(safe_search, "medium"),
        }

        if aspect_ratio and aspect_ratio in _ASPECT_RATIO_MAP:
            params["imgSize"] = _ASPECT_RATIO_MAP[aspect_ratio]

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


async def download_image(url: str, timeout: float = 30) -> Image.Image:
    """Download an image URL and return a PIL Image."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    return Image.open(io.BytesIO(resp.content))
