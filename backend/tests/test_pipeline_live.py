"""Live tests for the full pipeline.

These tests cost money! Run with: pytest -m live

Tests the complete flow: create asset -> process -> approve
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
import numpy as np
from PIL import Image

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models import InputItem, PipelineStep, StepType, StyleConfig, ProjectConfig

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


# Skip all tests if no API key
pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(
        not os.getenv("GOOGLE_API_KEY"),
        reason="GOOGLE_API_KEY not set - skipping live API tests"
    ),
]


@pytest_asyncio.fixture
async def live_project(tmp_path):
    """Create a project for live testing."""
    from pipeline import Project
    
    project_dir = tmp_path / "live_test_project"
    project_dir.mkdir()
    
    # Configure for cheap/fast generation
    config = ProjectConfig(
        name="Live Test Project",
        style=StyleConfig(
            aspect_ratio="1:1",
            image_size="1K",
        ),
        pipeline=[
            PipelineStep(
                id="generate_image",
                type=StepType.GENERATE_IMAGE,
                variations=1,  # Just 1 to save money
                requires_approval=False,  # Auto-approve for testing
            ),
        ],
    )
    
    original_cwd = os.getcwd()
    os.chdir(project_dir)
    
    project = await Project.init(project_dir, config)
    
    yield project
    
    os.chdir(original_cwd)


@pytest.mark.anyio
class TestPipelineExecution:
    """Test full pipeline execution with real APIs."""
    
    async def test_process_single_asset(self, live_project):
        """Process a single asset and verify image dimensions."""
        from pipeline import PipelineOrchestrator
        
        # Create an asset
        item = InputItem(description="A simple red dot")
        asset = await live_project.create_asset(item)
        
        assert asset.status.value == "pending"
        
        # Process it
        orchestrator = PipelineOrchestrator(live_project)
        result = await orchestrator.process_asset(asset, auto_approve=True)
        
        assert result.status.value == "completed"
        assert "generate_image" in result.results
        
        step_result = result.results["generate_image"]
        assert step_result.status.value == "completed"
        assert len(step_result.variations) == 1
        assert step_result.variations[0].type == "image"
        
        # Check file was created
        assert step_result.variations[0].path is not None
        image_path = live_project.path / step_result.variations[0].path
        assert image_path.exists()
        
        # Verify image dimensions
        img = Image.open(image_path)
        assert img.width > 0, "Image width must be positive"
        assert img.height > 0, "Image height must be positive"
        
        # Verify metadata contains dimensions
        metadata = step_result.variations[0].metadata or {}
        if "width" in metadata:
            assert metadata["width"] == img.width
        if "height" in metadata:
            assert metadata["height"] == img.height
        
        # Save copy for visual inspection
        output_path = TEST_OUTPUT_DIR / "pipeline_single_asset.png"
        img.save(output_path)
        
        print(f"Generated image at: {image_path}")
        print(f"Dimensions: {img.width}x{img.height}, mode: {img.mode}")
        print(f"Saved copy to: {output_path}")
    
    async def test_process_with_name_generation(self, live_project):
        """Process asset with name generation step."""
        from pipeline import PipelineOrchestrator
        
        # Add name generation to pipeline
        live_project._config.pipeline = [
            PipelineStep(
                id="generate_name",
                type=StepType.GENERATE_NAME,
                variations=1,
                requires_approval=False,
            ),
        ]
        
        item = InputItem(description="A mystical forest creature")
        asset = await live_project.create_asset(item)
        
        orchestrator = PipelineOrchestrator(live_project)
        result = await orchestrator.process_asset(asset, auto_approve=True)
        
        assert result.status.value == "completed"
        assert "generate_name" in result.results
        
        name_result = result.results["generate_name"]
        assert name_result.variations[0].type == "name"
        assert name_result.variations[0].content is not None
        
        print(f"Generated name: {name_result.variations[0].content}")
    
    async def test_process_with_text_generation(self, live_project):
        """Process asset with text description step."""
        from pipeline import PipelineOrchestrator
        
        live_project._config.pipeline = [
            PipelineStep(
                id="generate_description",
                type=StepType.GENERATE_TEXT,
                variations=1,
                requires_approval=False,
            ),
        ]
        
        item = InputItem(description="A brave knight")
        asset = await live_project.create_asset(item)
        
        orchestrator = PipelineOrchestrator(live_project)
        result = await orchestrator.process_asset(asset, auto_approve=True)
        
        assert result.status.value == "completed"
        
        text_result = result.results["generate_description"]
        assert text_result.variations[0].type == "text"
        assert len(text_result.variations[0].content) > 10
        
        print(f"Generated description: {text_result.variations[0].content[:100]}...")
    
    async def test_process_with_background_removal(self, live_project):
        """Process asset with image generation and background removal."""
        from pipeline import PipelineOrchestrator
        
        # Configure pipeline: generate image, then remove background
        live_project._config.pipeline = [
            PipelineStep(
                id="generate_image",
                type=StepType.GENERATE_IMAGE,
                variations=1,
                requires_approval=False,
            ),
            PipelineStep(
                id="remove_bg",
                type=StepType.REMOVE_BACKGROUND,
                config={"source_step": "generate_image"},
                requires_approval=False,
            ),
        ]
        
        # Create asset with a subject that can be isolated
        item = InputItem(description="A red apple, simple illustration on plain background")
        asset = await live_project.create_asset(item)
        
        orchestrator = PipelineOrchestrator(live_project)
        result = await orchestrator.process_asset(asset, auto_approve=True)
        
        assert result.status.value == "completed"
        assert "generate_image" in result.results
        assert "remove_bg" in result.results
        
        # Verify image step
        img_result = result.results["generate_image"]
        assert img_result.status.value == "completed"
        original_path = live_project.path / img_result.variations[0].path
        original_img = Image.open(original_path)
        
        # Verify background removal step
        bg_result = result.results["remove_bg"]
        assert bg_result.status.value == "completed"
        assert bg_result.variations[0].type == "image"
        
        # Check the output image
        sprite_path = live_project.path / bg_result.variations[0].path
        assert sprite_path.exists(), "Background-removed image not found"
        
        sprite_img = Image.open(sprite_path)
        
        # Verify dimensions preserved
        assert sprite_img.width == original_img.width
        assert sprite_img.height == original_img.height
        
        # Verify it's RGBA (has alpha channel)
        assert sprite_img.mode == "RGBA", f"Expected RGBA for sprite, got {sprite_img.mode}"
        
        # Verify significant transparency (background was removed)
        transparent_count, total_count, transparency_pct = count_transparent_pixels(sprite_img)
        
        print(f"Original: {original_img.width}x{original_img.height}, mode={original_img.mode}")
        print(f"Sprite: {sprite_img.width}x{sprite_img.height}, mode={sprite_img.mode}")
        print(f"Transparency: {transparent_count}/{total_count} pixels ({transparency_pct:.1%})")
        
        # At least 10% of pixels should be transparent (background removed)
        assert transparency_pct >= 0.10, (
            f"Expected at least 10% transparent pixels after background removal, "
            f"got {transparency_pct:.1%}. Background removal may have failed."
        )
        
        # But not all pixels - should still have the subject
        assert transparency_pct < 0.95, (
            f"Expected less than 95% transparency (need some subject visible), "
            f"got {transparency_pct:.1%}"
        )
        
        # Verify metadata marks it as transparent
        metadata = bg_result.variations[0].metadata or {}
        assert metadata.get("transparent") is True
        
        # Save copies for visual inspection
        original_output = TEST_OUTPUT_DIR / "pipeline_bg_removal_original.png"
        sprite_output = TEST_OUTPUT_DIR / "pipeline_bg_removal_sprite.png"
        original_img.save(original_output)
        sprite_img.save(sprite_output)
        print(f"Saved original to: {original_output}")
        print(f"Saved sprite to: {sprite_output}")


@pytest.mark.anyio
class TestEndToEndAPI:
    """Test full API flow with real generation."""
    
    async def test_upload_and_process(self, live_project):
        """Upload input and process via API."""
        from httpx import AsyncClient, ASGITransport
        import app.main as main_module
        from app.main import app
        
        # Point the app at our test project
        main_module._project = live_project
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Upload input
            response = await client.post(
                "/assets/upload",
                json={
                    "content": "A green triangle",
                    "format": "text",
                },
            )
            assert response.status_code == 200
            assets = response.json()["assets"]
            assert len(assets) == 1
            asset_id = assets[0]["id"]
            
            # Process with auto-approve
            response = await client.post(
                f"/assets/{asset_id}/process?auto_approve=true",
                timeout=60.0,
            )
            assert response.status_code == 200
            
            # Wait a moment for background processing
            import asyncio
            await asyncio.sleep(5)
            
            # Check asset status
            response = await client.get(f"/assets/{asset_id}")
            asset = response.json()
            
            # Should be completed or still processing
            assert asset["status"] in ["completed", "processing", "awaiting_approval"]
            print(f"Asset status: {asset['status']}")
        
        main_module._project = None
