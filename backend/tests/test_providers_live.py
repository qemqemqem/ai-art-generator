"""Live tests that hit real AI APIs.

These tests cost money! Run with: pytest -m live

They're designed to be as cheap as possible:
- 1 variation only
- Smallest output size
- Simple prompts
"""

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
import numpy as np
from PIL import Image

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import get_config
from app.models import StyleConfig

# Directory for saving test outputs for visual inspection
TEST_OUTPUT_DIR = Path(__file__).parent / "output"
TEST_OUTPUT_DIR.mkdir(exist_ok=True)


def count_transparent_pixels(img: Image.Image) -> tuple[int, int, float]:
    """Count transparent pixels in an image."""
    if img.mode != "RGBA":
        return 0, img.width * img.height, 0.0
    
    pixels = np.array(img)
    alpha_channel = pixels[:, :, 3]
    total = alpha_channel.size
    transparent = np.sum(alpha_channel < 128)
    return transparent, total, transparent / total


# Skip all tests in this file if no API key
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.getenv("GOOGLE_API_KEY"),
        reason="GOOGLE_API_KEY not set - skipping live API tests"
    ),
]


@pytest.fixture(scope="module")
def config():
    """Get app config with API keys."""
    return get_config()


class TestGeminiImageProvider:
    """Test Gemini/Nano Banana image generation."""
    
    @pytest.mark.anyio
    async def test_generate_single_image(self, config):
        """Generate a single image with Gemini and verify dimensions."""
        from providers.gemini import GeminiImageProvider
        
        provider = GeminiImageProvider(use_pro=False)
        
        # Minimal generation: 1 image, simple prompt
        images = await provider.generate(
            prompt="A red circle on white background",
            variations=1,
            style=StyleConfig(aspect_ratio="1:1"),
        )
        
        assert len(images) == 1
        img = images[0]
        
        # Verify image has valid dimensions
        assert img.width > 0, "Image width must be positive"
        assert img.height > 0, "Image height must be positive"
        
        # For 1:1 aspect ratio, width and height should be equal (or close)
        aspect_ratio = img.width / img.height
        assert 0.9 <= aspect_ratio <= 1.1, f"Expected ~1:1 ratio, got {aspect_ratio}"
        
        # Verify it's a valid image we can work with
        assert img.mode in ("RGB", "RGBA"), f"Unexpected image mode: {img.mode}"
        
        # Save for visual inspection
        output_path = TEST_OUTPUT_DIR / "test_generate_single_image.png"
        img.save(output_path)
        print(f"Generated image: {img.width}x{img.height}, mode={img.mode}")
        print(f"Saved to: {output_path}")
    
    @pytest.mark.anyio
    async def test_generate_with_style(self, config):
        """Generate with style prefix/suffix and verify dimensions."""
        from providers.gemini import GeminiImageProvider
        
        provider = GeminiImageProvider(use_pro=False)
        
        style = StyleConfig(
            global_prompt_prefix="pixel art",
            global_prompt_suffix="8-bit style",
            aspect_ratio="1:1",
        )
        
        images = await provider.generate(
            prompt="a small house",
            variations=1,
            style=style,
        )
        
        assert len(images) == 1
        img = images[0]
        
        # Verify dimensions
        assert img.width > 0
        assert img.height > 0
        
        # Verify 1:1 aspect ratio
        aspect_ratio = img.width / img.height
        assert 0.9 <= aspect_ratio <= 1.1
        
        # Save for visual inspection
        output_path = TEST_OUTPUT_DIR / "test_generate_with_style_pixelart.png"
        img.save(output_path)
        print(f"Generated styled image: {img.width}x{img.height}")
        print(f"Saved to: {output_path}")


class TestGeminiTextProvider:
    """Test Gemini text generation."""
    
    @pytest.mark.anyio
    async def test_generate_text(self, config):
        """Generate simple text."""
        from providers.gemini import GeminiTextProvider
        
        provider = GeminiTextProvider()
        
        result = await provider.generate(
            prompt="Say 'hello' and nothing else.",
            max_tokens=10,
        )
        
        assert len(result) > 0
        assert "hello" in result.lower()
        print(f"Generated text: {result}")
    
    @pytest.mark.anyio
    async def test_generate_structured(self, config):
        """Generate structured JSON output."""
        from providers.gemini import GeminiTextProvider
        
        provider = GeminiTextProvider()
        
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "color": {"type": "string"},
            },
        }
        
        result = await provider.generate_structured(
            prompt="Generate a name and color for a fantasy creature.",
            schema=schema,
        )
        
        assert "name" in result
        assert "color" in result
        print(f"Generated structured: {result}")


class TestProviderRegistry:
    """Test the provider registry with real providers."""
    
    def test_get_image_provider(self):
        """Get Gemini image provider from registry."""
        from providers import get_provider_registry
        
        registry = get_provider_registry()
        provider = registry.get_image_provider("gemini")
        
        assert provider is not None
        assert provider.name == "gemini"
    
    def test_get_text_provider(self):
        """Get Gemini text provider from registry."""
        from providers import get_provider_registry
        
        registry = get_provider_registry()
        provider = registry.get_text_provider("gemini")
        
        assert provider is not None
        assert provider.name == "gemini"
    
    def test_list_providers(self):
        """List available providers."""
        from providers import get_provider_registry
        
        registry = get_provider_registry()
        
        image_providers = registry.list_image_providers()
        text_providers = registry.list_text_providers()
        
        assert "gemini" in image_providers
        assert "gemini_pro" in image_providers
        assert "gemini" in text_providers


class TestBackgroundRemoval:
    """Test background removal with transparency verification."""
    
    @pytest.mark.anyio
    async def test_remove_background_creates_transparency(self, config):
        """Generate an image and remove background, verify transparency."""
        from providers.gemini import GeminiImageProvider
        from rembg import remove
        
        provider = GeminiImageProvider(use_pro=False)
        
        # Generate an image with a clear subject on background
        images = await provider.generate(
            prompt="A red apple on a white table, simple illustration",
            variations=1,
            style=StyleConfig(aspect_ratio="1:1"),
        )
        
        assert len(images) == 1
        original = images[0]
        
        # Save original for comparison
        original_path = TEST_OUTPUT_DIR / "test_bg_removal_original.png"
        original.save(original_path)
        print(f"Saved original to: {original_path}")
        
        # Verify original is RGB (no transparency)
        original_transparent, _, original_pct = count_transparent_pixels(original)
        print(f"Original image: {original.width}x{original.height}, transparency: {original_pct:.1%}")
        
        # Remove background
        result = remove(original)
        
        # Result should be RGBA
        assert result.mode == "RGBA", f"Expected RGBA, got {result.mode}"
        
        # Verify dimensions are preserved
        assert result.width == original.width
        assert result.height == original.height
        
        # Count transparent pixels
        transparent_count, total_count, transparency_pct = count_transparent_pixels(result)
        
        print(f"After removal: {result.width}x{result.height}")
        print(f"Transparent pixels: {transparent_count}/{total_count} ({transparency_pct:.1%})")
        
        # Should have significant transparency (background removed)
        # At least 10% of pixels should be transparent
        assert transparency_pct >= 0.10, (
            f"Expected at least 10% transparency after background removal, "
            f"got {transparency_pct:.1%}"
        )
        
        # Should still have some opaque pixels (the subject)
        opaque_pct = 1 - transparency_pct
        assert opaque_pct >= 0.05, (
            f"Expected at least 5% opaque pixels (the subject), "
            f"got {opaque_pct:.1%}"
        )
        
        # Save for visual inspection
        result_path = TEST_OUTPUT_DIR / "test_bg_removal_transparent.png"
        result.save(result_path)
        print(f"Saved transparent result to: {result_path}")


@pytest.mark.anyio
class TestQuickGenerateEndpoint:
    """Test the /generate endpoint with real API."""
    
    async def test_quick_generate(self, config):
        """Quick generate endpoint returns base64 image with correct size."""
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        import base64
        from io import BytesIO
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/generate",
                json={
                    "prompt": "A blue square",
                    "provider": "gemini",
                    "variations": 1,
                },
                timeout=60.0,
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "images" in data
        assert len(data["images"]) == 1
        
        img_data = data["images"][0]
        assert img_data["data"].startswith("data:image/png;base64,")
        
        # Verify reported dimensions
        assert img_data["width"] > 0
        assert img_data["height"] > 0
        
        # Decode and verify actual image dimensions match reported
        b64_data = img_data["data"].split(",")[1]
        img_bytes = base64.b64decode(b64_data)
        img = Image.open(BytesIO(img_bytes))
        
        assert img.width == img_data["width"], "Reported width doesn't match actual"
        assert img.height == img_data["height"], "Reported height doesn't match actual"
        
        # Save for visual inspection
        output_path = TEST_OUTPUT_DIR / "test_quick_generate_api.png"
        img.save(output_path)
        print(f"Quick generate: {img.width}x{img.height}, verified dimensions match")
        print(f"Saved to: {output_path}")
