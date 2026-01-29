"""Tests for image processing utilities.

These tests don't hit APIs - they test image manipulation locally.
"""

import sys
from pathlib import Path
from io import BytesIO

import pytest
from PIL import Image
import numpy as np

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestImageSizeVerification:
    """Test that we can verify image dimensions."""
    
    def test_create_image_with_size(self):
        """Create an image and verify its dimensions."""
        width, height = 512, 512
        img = Image.new("RGB", (width, height), color="red")
        
        assert img.width == width
        assert img.height == height
        assert img.mode == "RGB"
    
    def test_various_aspect_ratios(self):
        """Test creating images with different aspect ratios."""
        test_cases = [
            ((512, 512), "1:1"),
            ((768, 512), "3:2"),
            ((512, 768), "2:3"),
            ((1024, 576), "16:9"),
        ]
        
        for (width, height), ratio in test_cases:
            img = Image.new("RGB", (width, height), color="blue")
            assert img.width == width
            assert img.height == height
    
    def test_image_save_and_load_preserves_size(self, tmp_path):
        """Verify size is preserved through save/load cycle."""
        width, height = 256, 384
        img = Image.new("RGB", (width, height), color="green")
        
        filepath = tmp_path / "test_image.png"
        img.save(filepath)
        
        loaded = Image.open(filepath)
        assert loaded.width == width
        assert loaded.height == height


class TestBackgroundRemovalTransparency:
    """Test background removal and transparency detection."""
    
    def test_rgb_image_has_no_transparency(self):
        """RGB images should have no transparency."""
        img = Image.new("RGB", (100, 100), color="red")
        
        # RGB mode has no alpha channel
        assert img.mode == "RGB"
        assert "A" not in img.getbands()
    
    def test_rgba_image_can_have_transparency(self):
        """RGBA images can have transparent pixels."""
        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 255))
        
        assert img.mode == "RGBA"
        assert "A" in img.getbands()
        
        # All pixels are opaque (alpha=255)
        pixels = np.array(img)
        alpha_channel = pixels[:, :, 3]
        assert np.all(alpha_channel == 255)
    
    def test_create_image_with_transparent_background(self):
        """Create an image with transparent regions."""
        # Create a 100x100 image with transparent background
        img = Image.new("RGBA", (100, 100), color=(0, 0, 0, 0))
        
        # Draw a red circle in the center (50x50)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.ellipse([25, 25, 75, 75], fill=(255, 0, 0, 255))
        
        pixels = np.array(img)
        alpha_channel = pixels[:, :, 3]
        
        # Count transparent vs opaque pixels
        transparent_count = np.sum(alpha_channel == 0)
        opaque_count = np.sum(alpha_channel == 255)
        total = 100 * 100
        
        # Most of the image should be transparent (circle is ~1963 pixels)
        assert transparent_count > opaque_count
        assert transparent_count > total * 0.5  # At least 50% transparent
    
    def test_calculate_transparency_percentage(self):
        """Calculate what percentage of an image is transparent."""
        # Create image: 75% transparent, 25% opaque
        img = Image.new("RGBA", (100, 100), color=(0, 0, 0, 0))
        
        # Fill bottom-right quadrant with opaque red
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.rectangle([50, 50, 100, 100], fill=(255, 0, 0, 255))
        
        pixels = np.array(img)
        alpha_channel = pixels[:, :, 3]
        
        total_pixels = alpha_channel.size
        transparent_pixels = np.sum(alpha_channel == 0)
        transparency_pct = transparent_pixels / total_pixels
        
        assert abs(transparency_pct - 0.75) < 0.01  # ~75% transparent
    
    def test_rembg_integration(self):
        """Test rembg background removal on a simple image."""
        from rembg import remove
        
        # Create a simple test image: white background with red circle
        img = Image.new("RGB", (100, 100), color=(255, 255, 255))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.ellipse([20, 20, 80, 80], fill=(255, 0, 0))
        
        # Remove background
        result = remove(img)
        
        # Result should be RGBA
        assert result.mode == "RGBA"
        
        # Convert to numpy for analysis
        pixels = np.array(result)
        alpha_channel = pixels[:, :, 3]
        
        # Some pixels should be transparent (the white background)
        transparent_count = np.sum(alpha_channel < 128)
        opaque_count = np.sum(alpha_channel >= 128)
        
        # The white background regions should be at least partially transparent
        assert transparent_count > 0, "Background removal didn't create any transparency"
        
        # The circle should remain (at least some opaque pixels)
        assert opaque_count > 0, "Background removal removed everything"
        
        print(f"Transparent pixels: {transparent_count}, Opaque pixels: {opaque_count}")


class TestImageFormatConversion:
    """Test image format conversions."""
    
    def test_png_preserves_transparency(self, tmp_path):
        """PNG format should preserve alpha channel."""
        # Create image with transparency
        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        
        filepath = tmp_path / "test.png"
        img.save(filepath)
        
        loaded = Image.open(filepath)
        assert loaded.mode == "RGBA"
        
        # Check alpha is preserved
        pixels = np.array(loaded)
        assert np.all(pixels[:, :, 3] == 128)
    
    def test_jpeg_loses_transparency(self, tmp_path):
        """JPEG format cannot have transparency."""
        # Create image with transparency
        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        
        filepath = tmp_path / "test.jpg"
        # JPEG requires RGB mode
        img_rgb = img.convert("RGB")
        img_rgb.save(filepath)
        
        loaded = Image.open(filepath)
        assert loaded.mode == "RGB"
        assert "A" not in loaded.getbands()


def count_transparent_pixels(img: Image.Image) -> tuple[int, int, float]:
    """
    Count transparent pixels in an image.
    
    Returns:
        (transparent_count, total_count, transparency_percentage)
    """
    if img.mode != "RGBA":
        return 0, img.width * img.height, 0.0
    
    pixels = np.array(img)
    alpha_channel = pixels[:, :, 3]
    
    total = alpha_channel.size
    transparent = np.sum(alpha_channel < 128)  # Less than half opacity = transparent
    
    return transparent, total, transparent / total


class TestTransparencyHelper:
    """Test the transparency counting helper."""
    
    def test_fully_opaque_image(self):
        """Fully opaque image has 0% transparency."""
        img = Image.new("RGBA", (50, 50), color=(255, 0, 0, 255))
        
        transparent, total, pct = count_transparent_pixels(img)
        
        assert transparent == 0
        assert total == 2500
        assert pct == 0.0
    
    def test_fully_transparent_image(self):
        """Fully transparent image has 100% transparency."""
        img = Image.new("RGBA", (50, 50), color=(0, 0, 0, 0))
        
        transparent, total, pct = count_transparent_pixels(img)
        
        assert transparent == 2500
        assert total == 2500
        assert pct == 1.0
    
    def test_half_transparent_image(self):
        """Half transparent image has 50% transparency."""
        img = Image.new("RGBA", (100, 100), color=(0, 0, 0, 0))
        
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        # Fill left half with opaque red
        draw.rectangle([0, 0, 50, 100], fill=(255, 0, 0, 255))
        
        transparent, total, pct = count_transparent_pixels(img)
        
        assert total == 10000
        assert abs(pct - 0.5) <= 0.02  # Approximately 50% (within 2%)
    
    def test_rgb_image_has_zero_transparency(self):
        """RGB images report 0% transparency."""
        img = Image.new("RGB", (50, 50), color="red")
        
        transparent, total, pct = count_transparent_pixels(img)
        
        assert transparent == 0
        assert pct == 0.0
