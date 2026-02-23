"""Live tests for image_search stage using SerpAPI.

These tests hit the real SerpAPI Google Images endpoint.
Run with: pytest -m live tests/test_image_search_live.py

Requires SERPAPI_API_KEY to be set.
"""

import os
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.image_search import (
    SerpAPISearchProvider,
    ImageSearchResult,
    download_image,
)

TEST_OUTPUT_DIR = Path(__file__).parent / "output"
TEST_OUTPUT_DIR.mkdir(exist_ok=True)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.getenv("SERPAPI_API_KEY") or os.getenv("SERPAPI_API_KEY", "").startswith("your_"),
        reason="SERPAPI_API_KEY not configured - get one at https://serpapi.com/",
    ),
]


class TestSerpAPISearchProvider:
    """Test SerpAPI Google Images search with real API calls."""

    @pytest.mark.anyio
    async def test_search_returns_results(self):
        """Basic search returns at least one result with expected fields."""
        provider = SerpAPISearchProvider()
        results = await provider.search("blue jay bird photo", count=1)

        assert len(results) >= 1
        result = results[0]
        assert isinstance(result, ImageSearchResult)
        assert result.url.startswith("http")
        assert result.width > 0
        assert result.height > 0
        assert len(result.title) > 0
        print(f"Result: {result.title} ({result.width}x{result.height})")
        print(f"  URL: {result.url}")

    @pytest.mark.anyio
    async def test_search_respects_count(self):
        """Requesting N results returns up to N results."""
        provider = SerpAPISearchProvider()
        results = await provider.search("cardinal bird", count=3)

        assert 1 <= len(results) <= 3
        print(f"Requested 3, got {len(results)} results")
        for i, r in enumerate(results):
            print(f"  [{i}] {r.title} ({r.width}x{r.height})")

    @pytest.mark.anyio
    async def test_search_with_aspect_ratio(self):
        """Aspect ratio filter is accepted by the API."""
        provider = SerpAPISearchProvider()

        for ratio in ("landscape", "portrait", "square"):
            results = await provider.search(
                "robin bird", count=1, aspect_ratio=ratio,
            )
            assert len(results) >= 1, f"No results for aspect_ratio={ratio}"
            print(f"  {ratio}: {results[0].width}x{results[0].height}")

    @pytest.mark.anyio
    async def test_search_with_image_type(self):
        """Image type filter (photo) is accepted by the API."""
        provider = SerpAPISearchProvider()
        results = await provider.search(
            "eagle bird", count=1, image_type="photo",
        )

        assert len(results) >= 1
        print(f"Photo filter: {results[0].title}")

    @pytest.mark.anyio
    async def test_search_with_safe_search(self):
        """Safe search parameter is accepted by the API."""
        provider = SerpAPISearchProvider()
        results = await provider.search(
            "parrot bird", count=1, safe_search="strict",
        )

        assert len(results) >= 1
        print(f"Strict safe search: {results[0].title}")


class TestDownloadImage:
    """Test downloading search results to PIL Images."""

    @pytest.mark.anyio
    async def test_download_and_save(self):
        """Search for an image, download it, and verify it's a valid PIL Image."""
        provider = SerpAPISearchProvider()
        results = await provider.search(
            "hummingbird wildlife photograph", count=1, image_type="photo",
        )
        assert len(results) >= 1

        img = await download_image(results[0].url)
        assert isinstance(img, Image.Image)
        assert img.width > 0
        assert img.height > 0

        output_path = TEST_OUTPUT_DIR / "test_image_search_download.png"
        img.save(output_path)
        print(f"Downloaded: {img.width}x{img.height}, mode={img.mode}")
        print(f"Saved to: {output_path}")

    @pytest.mark.anyio
    async def test_download_multiple(self):
        """Download multiple search results and save them all."""
        provider = SerpAPISearchProvider()
        results = await provider.search(
            "owl bird photo", count=3, image_type="photo",
        )
        assert len(results) >= 1

        downloaded = 0
        for i, result in enumerate(results):
            try:
                img = await download_image(result.url)
                output_path = TEST_OUTPUT_DIR / f"test_image_search_multi_{i}.png"
                img.save(output_path)
                downloaded += 1
                print(f"  [{i}] {img.width}x{img.height} -> {output_path}")
            except Exception as exc:
                print(f"  [{i}] Failed to download {result.url}: {exc}")

        assert downloaded >= 1, "At least one image should download successfully"
        print(f"Downloaded {downloaded}/{len(results)} images")
