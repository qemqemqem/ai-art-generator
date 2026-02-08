"""
Image Generation Executors.

Handles image-based steps:
  - generate_image: General image generation
  - generate_sprite: Pixel art sprite generation with transparency
  - remove_background: Remove background from images
  - resize: Resize images to multiple sizes
"""

from pathlib import Path
from typing import Any

from PIL import Image

from .base import ExecutorContext, StepExecutor, StepResult
from .registry import register_executor
from ..templates import substitute_template


def _count_transparent_pixels(img: Image.Image, alpha_threshold: int) -> tuple[int, int, float]:
    """Count transparent pixels using an alpha threshold."""
    if img.mode != "RGBA":
        return 0, img.width * img.height, 0.0
    
    alpha_channel = img.getchannel("A")
    histogram = alpha_channel.histogram()
    transparent = sum(histogram[:alpha_threshold])
    total = img.width * img.height
    return transparent, total, transparent / total


@register_executor("generate_image")
class GenerateImageExecutor(StepExecutor):
    """Execute image generation steps."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute an image generation step.
        
        Config:
            prompt: The image generation prompt
            variations: Number of images to generate
            size: Image size (default: 512)
            model: Specific model to use
        """
        import time
        start = time.time()
        
        prompt = config.get("prompt", "")
        variations = config.get("variations", 1)
        size = config.get("size", 512)
        
        # Substitute template variables
        prompt = substitute_template(
            prompt,
            ctx.context,
            ctx.asset,
            ctx.step_outputs,
        )
        
        # Get image provider (use context's configured provider)
        provider = ctx.providers.get_image_provider(ctx.image_provider)
        
        from app.models import StyleConfig
        
        style = StyleConfig(
            width=size,
            height=size,
        )
        
        images = await provider.generate(
            prompt=prompt,
            style=style,
            variations=variations,
        )
        
        # Save images
        output_paths = []
        for i, img in enumerate(images):
            path = self.get_image_output_path(ctx, "generate_image", i)
            img.save(path)
            output_paths.append(path)
        
        duration = int((time.time() - start) * 1000)
        
        return StepResult(
            success=True,
            output={"prompt": prompt, "paths": [str(p) for p in output_paths]},
            variations=[str(p) for p in output_paths],
            output_paths=output_paths,
            duration_ms=duration,
            prompt=prompt,
        )


@register_executor("generate_sprite")
class GenerateSpriteExecutor(StepExecutor):
    """Execute pixel art sprite generation steps."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute a sprite generation step.
        
        Config:
            prompt: The sprite generation prompt
            variations: Number of sprites to generate
            size: Sprite size (default: 512)
            auto_remove_background: Remove background for transparency (default: True)
        """
        import time
        start = time.time()
        
        prompt = config.get("prompt", "")
        variations = config.get("variations", 1)
        size = config.get("size", 512)
        auto_remove_bg = config.get("auto_remove_background", True)
        
        # Substitute template variables
        prompt = substitute_template(
            prompt,
            ctx.context,
            ctx.asset,
            ctx.step_outputs,
        )
        
        # Enhance prompt for pixel art sprites
        # Use solid white background since AI can't create true transparency
        enhanced_prompt = f"Pixel art sprite, {prompt}, clean edges, suitable for video games, isolated on solid white background"
        
        # Get image provider (use context's configured provider)
        provider = ctx.providers.get_image_provider(ctx.image_provider)
        
        from app.models import StyleConfig
        
        style = StyleConfig(
            width=size,
            height=size,
            global_prompt_prefix="pixel art, 16-bit style, game sprite",
        )
        
        images = await provider.generate(
            prompt=enhanced_prompt,
            style=style,
            variations=variations,
        )
        
        # Remove background if requested
        if auto_remove_bg:
            from rembg import remove
            images = [remove(img) for img in images]
        
        # Save sprites
        output_paths = []
        step_id = config.get("_step_id", "generate_sprite")
        
        for i, img in enumerate(images):
            path = self.get_image_output_path(ctx, step_id, i)
            img.save(path)
            output_paths.append(path)
        
        duration = int((time.time() - start) * 1000)
        
        return StepResult(
            success=True,
            output={
                "prompt": prompt,
                "paths": [str(p) for p in output_paths],
                "transparent": auto_remove_bg,
            },
            variations=[str(p) for p in output_paths],
            output_paths=output_paths,
            duration_ms=duration,
            prompt=enhanced_prompt,
        )


@register_executor("remove_background")
class RemoveBackgroundExecutor(StepExecutor):
    """Execute background removal steps."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute a background removal step.
        
        Config:
            source_step: Step ID containing the source image
            source_index: Which variation to process (default: 0 or selected)
        """
        import time
        start = time.time()
        
        source_step = config.get("source_step", "generate_image")
        source_index = config.get("source_index", 0)
        min_transparency_pct = float(config.get("min_transparency_pct", 0.10))
        min_opaque_pct = float(config.get("min_opaque_pct", 0.05))
        alpha_threshold = config.get("alpha_threshold", 128)
        
        try:
            alpha_threshold = int(alpha_threshold)
        except (TypeError, ValueError):
            return StepResult(
                success=False,
                error=f"alpha_threshold must be an integer, got: {alpha_threshold}",
            )
        
        if alpha_threshold < 0 or alpha_threshold > 255:
            return StepResult(
                success=False,
                error=f"alpha_threshold must be between 0 and 255, got: {alpha_threshold}",
            )
        
        # Get source image path from previous step
        if source_step not in ctx.step_outputs:
            return StepResult(
                success=False,
                error=f"Source step '{source_step}' not found",
            )
        
        source_output = ctx.step_outputs[source_step]
        
        # Handle different output structures
        if isinstance(source_output, dict):
            if "selected_path" in source_output:
                source_path = Path(source_output["selected_path"])
            elif "paths" in source_output:
                paths = source_output["paths"]
                source_path = Path(paths[source_index])
            else:
                return StepResult(
                    success=False,
                    error=f"Cannot find image path in source step output",
                )
        else:
            return StepResult(
                success=False,
                error=f"Invalid source step output format",
            )
        
        if not source_path.exists():
            return StepResult(
                success=False,
                error=f"Source image not found: {source_path}",
            )
        
        from rembg import remove
        
        # Load and process image
        img = Image.open(source_path)
        result_img = remove(img)
        
        # Save result
        step_id = config.get("_step_id", "remove_background")
        output_path = self.get_image_output_path(ctx, step_id, 0)
        result_img.save(output_path)
        
        transparent_count, total_count, transparency_pct = _count_transparent_pixels(
            result_img, alpha_threshold
        )
        opaque_pct = 1.0 - transparency_pct
        
        if transparency_pct < min_transparency_pct:
            return StepResult(
                success=False,
                error=(
                    f"Background removal produced insufficient transparency "
                    f"({transparency_pct:.1%} < {min_transparency_pct:.1%}). "
                    f"Output: {output_path}"
                ),
            )
        
        if opaque_pct < min_opaque_pct:
            return StepResult(
                success=False,
                error=(
                    f"Background removal left too little subject opacity "
                    f"({opaque_pct:.1%} < {min_opaque_pct:.1%}). "
                    f"Output: {output_path}"
                ),
            )
        
        duration = int((time.time() - start) * 1000)
        
        return StepResult(
            success=True,
            output={
                "path": str(output_path),
                "source": str(source_path),
                "transparent_pixels": transparent_count,
                "total_pixels": total_count,
                "transparency_pct": transparency_pct,
                "opaque_pct": opaque_pct,
            },
            output_paths=[output_path],
            duration_ms=duration,
        )


@register_executor("resize")
class ResizeExecutor(StepExecutor):
    """Execute image resize steps."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute a resize step.
        
        Config:
            source_step: Step ID containing the source image
            sizes: List of output sizes (e.g., [32, 64, 128])
            format: Output format (default: "png")
        """
        import time
        start = time.time()
        
        source_step = config.get("source_step")
        sizes = config.get("sizes", [64, 128, 256])
        output_format = config.get("format", "png")
        
        # Find source image
        source_path = None
        
        if source_step and source_step in ctx.step_outputs:
            source_output = ctx.step_outputs[source_step]
            if isinstance(source_output, dict):
                if "selected_path" in source_output:
                    source_path = Path(source_output["selected_path"])
                elif "path" in source_output:
                    source_path = Path(source_output["path"])
                elif "paths" in source_output:
                    source_path = Path(source_output["paths"][0])
        
        if not source_path or not source_path.exists():
            return StepResult(
                success=False,
                error=f"Source image not found for resize",
            )
        
        img = Image.open(source_path)
        
        step_id = config.get("_step_id", "resize")
        output_paths = []
        
        for size in sizes:
            # Resize maintaining aspect ratio
            if isinstance(size, int):
                new_size = (size, size)
            else:
                new_size = tuple(size)
            
            resized = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # Determine output path
            if ctx.asset:
                asset_id = ctx.asset.get("id", f"asset-{ctx.asset_index:03d}")
                output_dir = ctx.state_dir / step_id / asset_id / "sizes"
            else:
                output_dir = ctx.state_dir / step_id / "sizes"
            
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{size}x{size}.{output_format}"
            
            resized.save(output_path)
            output_paths.append(output_path)
        
        duration = int((time.time() - start) * 1000)
        
        return StepResult(
            success=True,
            output={
                "paths": [str(p) for p in output_paths],
                "sizes": sizes,
            },
            output_paths=output_paths,
            duration_ms=duration,
        )
