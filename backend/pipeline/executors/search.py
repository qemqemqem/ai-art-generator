"""
Image Search Executor.

Searches the web for images matching a query and downloads the top results.
"""

import logging
import time
from typing import Any

from .base import ExecutorContext, StepExecutor, StepResult
from .registry import register_executor
from ..image_search import SerpAPISearchProvider, download_image
from ..templates import substitute_template

logger = logging.getLogger(__name__)


@register_executor("image_search")
class ImageSearchExecutor(StepExecutor):
    """Search for images on the web and download them."""

    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute an image search step.

        Config:
            query: Search query (supports template variables)
            count: Number of images to download (default: 1, max: 10)
            aspect_ratio: "square", "landscape", or "portrait" (optional)
            style: Additional search terms appended to query (optional)
            safe_search: "off", "moderate", or "strict" (default: "moderate")
            image_type: "photo", "clipart", "lineart", or "face" (optional)
        """
        start = time.time()

        query = config.get("query", "")
        count = config.get("count", 1)
        aspect_ratio = config.get("aspect_ratio")
        style = config.get("style")
        safe_search = config.get("safe_search", "moderate")
        image_type = config.get("image_type")

        query = substitute_template(
            query,
            ctx.context,
            ctx.asset,
            ctx.step_outputs,
        )

        if style:
            style = substitute_template(
                style,
                ctx.context,
                ctx.asset,
                ctx.step_outputs,
            )
            query = f"{query} {style}"

        fetch_count = min(count * 3, 10)
        provider = SerpAPISearchProvider()
        results = await provider.search(
            query,
            count=fetch_count,
            aspect_ratio=aspect_ratio,
            image_type=image_type,
            safe_search=safe_search,
        )

        if not results:
            return StepResult(
                success=False,
                error=f"No images found for query: {query}",
            )

        output_paths = []
        urls = []
        saved = 0
        for result in results:
            if saved >= count:
                break
            try:
                img = await download_image(result.url)
                path = self.get_image_output_path(ctx, "image_search", saved)
                img.save(path)
                output_paths.append(path)
                urls.append(result.url)
                saved += 1
            except Exception:
                logger.warning("Failed to download image: %s", result.url, exc_info=True)

        if not output_paths:
            return StepResult(
                success=False,
                error=f"All image downloads failed for query: {query}",
            )

        duration = int((time.time() - start) * 1000)

        return StepResult(
            success=True,
            output={
                "query": query,
                "paths": [str(p) for p in output_paths],
                "urls": urls,
            },
            variations=[str(p) for p in output_paths],
            output_paths=output_paths,
            duration_ms=duration,
            prompt=query,
        )
