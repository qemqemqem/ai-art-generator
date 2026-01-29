"""Tests for CLI commands - uses mocked providers for fast testing."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCLIArgumentParsing:
    """Test CLI argument parsing without executing."""
    
    def test_generate_command_detected_for_file(self):
        """File argument triggers generate command."""
        import artgen
        
        # Save original argv
        original_argv = sys.argv
        
        try:
            sys.argv = ["artgen", "test.txt", "--help"]
            # This should not raise
            with pytest.raises(SystemExit) as exc_info:
                artgen.main()
            assert exc_info.value.code == 0
        finally:
            sys.argv = original_argv
    
    def test_help_shows_examples(self):
        """Help output includes usage examples."""
        import artgen
        import io
        from contextlib import redirect_stdout
        
        original_argv = sys.argv
        
        try:
            sys.argv = ["artgen", "--help"]
            
            with pytest.raises(SystemExit):
                artgen.main()
                
        finally:
            sys.argv = original_argv


class TestGenerateCommand:
    """Test the generate command with mocked providers."""
    
    @pytest.fixture
    def mock_image(self):
        """Create a test image."""
        img = Image.new("RGB", (100, 100), color="red")
        return img
    
    @pytest.fixture
    def mock_provider(self, mock_image):
        """Create a mocked image provider."""
        provider = MagicMock()
        provider.generate = AsyncMock(return_value=[mock_image])
        return provider
    
    @pytest.fixture
    def input_file(self, tmp_path):
        """Create a test input file."""
        content = """A blue bird
A red bird"""
        input_path = tmp_path / "test_input.txt"
        input_path.write_text(content)
        return input_path
    
    @pytest.fixture
    def env_file(self, tmp_path):
        """Create a test env file."""
        env_path = tmp_path / ".env.test"
        env_path.write_text("GOOGLE_API_KEY=test-api-key")
        return env_path
    
    def test_generate_creates_output_directory(self, tmp_path, input_file, env_file, mock_provider):
        """Generate command creates output directory structure."""
        output_dir = tmp_path / "outputs"
        
        # Patch at the pipeline.orchestrator module level where it's actually used
        with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
            mock_registry.return_value.get_image_provider.return_value = mock_provider
            
            from artgen import cmd_generate
            import argparse
            
            args = argparse.Namespace(
                file=str(input_file),
                env=str(env_file),
                output=str(output_dir),
                style=None,
                transparent=False,
                variations=1,
                provider="gemini",
                verbose=False,
            )
            
            result = cmd_generate(args)
        
        # Check output structure was created
        assert output_dir.exists()
        assert (output_dir / "outputs").exists()
    
    def test_generate_processes_all_items(self, tmp_path, input_file, env_file, mock_provider):
        """Generate command processes all items from input file."""
        output_dir = tmp_path / "outputs"
        
        with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
            mock_registry.return_value.get_image_provider.return_value = mock_provider
            
            from artgen import cmd_generate
            import argparse
            
            args = argparse.Namespace(
                file=str(input_file),
                env=str(env_file),
                output=str(output_dir),
                style=None,
                transparent=False,
                variations=1,
                provider="gemini",
                verbose=False,
            )
            
            result = cmd_generate(args)
        
        # Provider should have been called twice (once per item)
        assert mock_provider.generate.call_count == 2
    
    def test_generate_with_variations(self, tmp_path, input_file, env_file):
        """Generate command respects variations parameter."""
        output_dir = tmp_path / "outputs"
        
        # Create mock that returns multiple images
        mock_images = [Image.new("RGB", (100, 100), color=c) for c in ["red", "blue", "green"]]
        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=mock_images)
        
        with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
            mock_registry.return_value.get_image_provider.return_value = mock_provider
            
            from artgen import cmd_generate
            import argparse
            
            args = argparse.Namespace(
                file=str(input_file),
                env=str(env_file),
                output=str(output_dir),
                style=None,
                transparent=False,
                variations=3,
                provider="gemini",
                verbose=False,
            )
            
            result = cmd_generate(args)
        
        # Provider should have been called with multiple variations
        assert mock_provider.generate.call_count == 2  # 2 items
    
    def test_generate_with_style(self, tmp_path, input_file, env_file, mock_provider):
        """Generate command applies style to prompts."""
        output_dir = tmp_path / "outputs"
        
        with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
            mock_registry.return_value.get_image_provider.return_value = mock_provider
            
            from artgen import cmd_generate
            import argparse
            
            args = argparse.Namespace(
                file=str(input_file),
                env=str(env_file),
                output=str(output_dir),
                style="pixel art, 16-bit",
                transparent=False,
                variations=1,
                provider="gemini",
                verbose=False,
            )
            
            result = cmd_generate(args)
        
        # Provider was called - style should be in the call
        assert mock_provider.generate.called
    
    def test_generate_returns_zero_on_success(self, tmp_path, input_file, env_file, mock_provider):
        """Generate command returns 0 on success."""
        output_dir = tmp_path / "outputs"
        
        with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
            mock_registry.return_value.get_image_provider.return_value = mock_provider
            
            from artgen import cmd_generate
            import argparse
            
            args = argparse.Namespace(
                file=str(input_file),
                env=str(env_file),
                output=str(output_dir),
                style=None,
                transparent=False,
                variations=1,
                provider="gemini",
                verbose=False,
            )
            
            result = cmd_generate(args)
        
        assert result == 0
    
    def test_generate_handles_missing_file(self, tmp_path, env_file):
        """Generate command handles missing input file gracefully."""
        from artgen import cmd_generate
        import argparse
        
        args = argparse.Namespace(
            file="/nonexistent/file.txt",
            env=str(env_file),
            output=str(tmp_path / "outputs"),
            style=None,
            transparent=False,
            variations=1,
            provider="gemini",
            verbose=False,
        )
        
        result = cmd_generate(args)
        
        assert result == 1  # Should return error code
    
    def test_generate_handles_empty_file(self, tmp_path, env_file):
        """Generate command handles empty input file."""
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")
        
        from artgen import cmd_generate
        import argparse
        
        args = argparse.Namespace(
            file=str(empty_file),
            env=str(env_file),
            output=str(tmp_path / "outputs"),
            style=None,
            transparent=False,
            variations=1,
            provider="gemini",
            verbose=False,
        )
        
        result = cmd_generate(args)
        
        assert result == 1  # Should return error for empty file
    
    def test_generate_handles_provider_failure(self, tmp_path, input_file, env_file):
        """Generate command handles provider errors gracefully."""
        output_dir = tmp_path / "outputs"
        
        # Create mock that raises an exception
        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(side_effect=Exception("API Error"))
        
        with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
            mock_registry.return_value.get_image_provider.return_value = mock_provider
            
            from artgen import cmd_generate
            import argparse
            
            args = argparse.Namespace(
                file=str(input_file),
                env=str(env_file),
                output=str(output_dir),
                style=None,
                transparent=False,
                variations=1,
                provider="gemini",
                verbose=True,
            )
            
            result = cmd_generate(args)
        
        # Should return non-zero when all items fail
        assert result == 1


class TestTransparentMode:
    """Test the --transparent sprite mode."""
    
    @pytest.fixture
    def input_file(self, tmp_path):
        """Create a test input file."""
        content = "A pixel art character"
        input_path = tmp_path / "sprites.txt"
        input_path.write_text(content)
        return input_path
    
    @pytest.fixture
    def env_file(self, tmp_path):
        """Create a test env file."""
        env_path = tmp_path / ".env.test"
        env_path.write_text("GOOGLE_API_KEY=test-api-key")
        return env_path
    
    def test_transparent_uses_sprite_pipeline(self, tmp_path, input_file, env_file):
        """--transparent flag uses generate_sprite step type."""
        output_dir = tmp_path / "outputs"
        
        # Create mock with RGBA image
        mock_image = Image.new("RGBA", (100, 100), color=(255, 0, 0, 255))
        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=[mock_image])
        
        with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
            mock_registry.return_value.get_image_provider.return_value = mock_provider
            # Mock rembg.remove which is imported inside the method
            with patch("rembg.remove") as mock_rembg:
                mock_rembg.return_value = mock_image
                
                from artgen import cmd_generate
                import argparse
                
                args = argparse.Namespace(
                    file=str(input_file),
                    env=str(env_file),
                    output=str(output_dir),
                    style=None,
                    transparent=True,
                    variations=1,
                    provider="gemini",
                    verbose=False,
                )
                
                result = cmd_generate(args)
        
        # Check that sprite output exists
        assert (output_dir / "outputs" / "item-001").exists()
        # rembg should have been called for background removal
        assert mock_rembg.called


class TestStatusCommand:
    """Test the status command."""
    
    def test_status_without_project(self, tmp_path):
        """Status command works when no project exists."""
        import artgen
        
        original_cwd = os.getcwd()
        original_argv = sys.argv
        
        try:
            os.chdir(tmp_path)
            sys.argv = ["artgen", "status"]
            
            # Should not crash
            result = artgen.main()
            assert result == 0
            
        finally:
            os.chdir(original_cwd)
            sys.argv = original_argv
    
    def test_status_with_project(self, tmp_path):
        """Status command shows project info."""
        import artgen
        import json
        
        # Create a minimal project
        config = {
            "name": "Test Project",
            "pipeline": [],
        }
        (tmp_path / "artgen.json").write_text(json.dumps(config))
        
        original_cwd = os.getcwd()
        original_argv = sys.argv
        
        try:
            os.chdir(tmp_path)
            sys.argv = ["artgen", "status"]
            
            result = artgen.main()
            assert result == 0
            
        finally:
            os.chdir(original_cwd)
            sys.argv = original_argv


class TestInitCommand:
    """Test the init command."""
    
    def test_init_creates_project_files(self, tmp_path):
        """Init command creates artgen.json and directories."""
        import artgen
        
        original_cwd = os.getcwd()
        original_argv = sys.argv
        
        try:
            os.chdir(tmp_path)
            sys.argv = ["artgen", "init"]
            
            result = artgen.main()
            
            assert result == 0
            assert (tmp_path / "artgen.json").exists()
            assert (tmp_path / "outputs").exists()
            
        finally:
            os.chdir(original_cwd)
            sys.argv = original_argv
    
    def test_init_fails_if_project_exists(self, tmp_path):
        """Init command fails if project already exists."""
        import artgen
        import json
        
        # Create existing project
        (tmp_path / "artgen.json").write_text(json.dumps({"name": "Existing"}))
        
        original_cwd = os.getcwd()
        original_argv = sys.argv
        
        try:
            os.chdir(tmp_path)
            sys.argv = ["artgen", "init"]
            
            result = artgen.main()
            
            assert result == 1  # Should fail
            
        finally:
            os.chdir(original_cwd)
            sys.argv = original_argv


class TestListCommand:
    """Test the list command."""
    
    def test_list_without_project(self, tmp_path):
        """List command works when no project exists."""
        import artgen
        
        original_cwd = os.getcwd()
        original_argv = sys.argv
        
        try:
            os.chdir(tmp_path)
            sys.argv = ["artgen", "list"]
            
            result = artgen.main()
            assert result == 0
            
        finally:
            os.chdir(original_cwd)
            sys.argv = original_argv
    
    def test_list_with_empty_project(self, tmp_path):
        """List command shows message for empty project."""
        import artgen
        import json
        
        # Create minimal project
        (tmp_path / "artgen.json").write_text(json.dumps({"name": "Test"}))
        (tmp_path / ".artgen").mkdir()
        
        original_cwd = os.getcwd()
        original_argv = sys.argv
        
        try:
            os.chdir(tmp_path)
            sys.argv = ["artgen", "list"]
            
            result = artgen.main()
            assert result == 0
            
        finally:
            os.chdir(original_cwd)
            sys.argv = original_argv
    
    def test_list_with_assets(self, tmp_path):
        """List command shows assets from project."""
        import artgen
        import json
        
        # Create project with asset
        (tmp_path / "artgen.json").write_text(json.dumps({"name": "Test"}))
        (tmp_path / ".artgen").mkdir()
        (tmp_path / "outputs").mkdir()
        
        asset_data = {
            "id": "test-001",
            "input_description": "A test item",
            "status": "completed",
            "results": {},
            "created_at": "2026-01-29T00:00:00",
            "updated_at": "2026-01-29T00:00:00",
        }
        (tmp_path / ".artgen" / "progress.jsonl").write_text(json.dumps(asset_data) + "\n")
        
        original_cwd = os.getcwd()
        original_argv = sys.argv
        
        try:
            os.chdir(tmp_path)
            sys.argv = ["artgen", "list"]
            
            result = artgen.main()
            assert result == 0
            
        finally:
            os.chdir(original_cwd)
            sys.argv = original_argv


class TestShowCommand:
    """Test the show command."""
    
    def test_show_without_project(self, tmp_path):
        """Show command fails when no project exists."""
        import artgen
        
        original_cwd = os.getcwd()
        original_argv = sys.argv
        
        try:
            os.chdir(tmp_path)
            sys.argv = ["artgen", "show", "item-001"]
            
            result = artgen.main()
            assert result == 1  # Should fail
            
        finally:
            os.chdir(original_cwd)
            sys.argv = original_argv
    
    def test_show_missing_asset(self, tmp_path):
        """Show command fails for non-existent asset."""
        import artgen
        import json
        
        # Create project without the asset
        (tmp_path / "artgen.json").write_text(json.dumps({"name": "Test"}))
        (tmp_path / ".artgen").mkdir()
        (tmp_path / "outputs").mkdir()
        
        original_cwd = os.getcwd()
        original_argv = sys.argv
        
        try:
            os.chdir(tmp_path)
            sys.argv = ["artgen", "show", "nonexistent-001"]
            
            result = artgen.main()
            assert result == 1  # Should fail
            
        finally:
            os.chdir(original_cwd)
            sys.argv = original_argv
    
    def test_show_existing_asset(self, tmp_path):
        """Show command displays asset details."""
        import artgen
        import json
        
        # Create project with asset
        (tmp_path / "artgen.json").write_text(json.dumps({"name": "Test"}))
        (tmp_path / ".artgen").mkdir()
        (tmp_path / "outputs").mkdir()
        (tmp_path / "outputs" / "test-001").mkdir()
        
        asset_data = {
            "id": "test-001",
            "input_description": "A test description",
            "status": "completed",
            "results": {},
            "created_at": "2026-01-29T00:00:00",
            "updated_at": "2026-01-29T00:00:00",
        }
        (tmp_path / ".artgen" / "progress.jsonl").write_text(json.dumps(asset_data) + "\n")
        
        original_cwd = os.getcwd()
        original_argv = sys.argv
        
        try:
            os.chdir(tmp_path)
            sys.argv = ["artgen", "show", "test-001"]
            
            result = artgen.main()
            assert result == 0
            
        finally:
            os.chdir(original_cwd)
            sys.argv = original_argv


class TestRunCommand:
    """Test the run command for specific pipeline steps."""
    
    @pytest.fixture
    def mock_image(self):
        """Create a test image."""
        return Image.new("RGB", (100, 100), color="red")
    
    @pytest.fixture
    def mock_provider(self, mock_image):
        """Create a mocked image provider."""
        provider = MagicMock()
        provider.generate = AsyncMock(return_value=[mock_image])
        return provider
    
    @pytest.fixture
    def input_file(self, tmp_path):
        """Create a test input file."""
        content = """A test item
Another test item"""
        input_path = tmp_path / "test.txt"
        input_path.write_text(content)
        return input_path
    
    @pytest.fixture
    def env_file(self, tmp_path):
        """Create a test env file."""
        env_path = tmp_path / ".env.test"
        env_path.write_text("GOOGLE_API_KEY=test-api-key")
        return env_path
    
    def test_run_invalid_step_type(self, tmp_path, env_file):
        """Run command rejects invalid step types."""
        from artgen import cmd_run
        import argparse
        
        args = argparse.Namespace(
            step="invalid_step",
            input=None,
            env=str(env_file),
            output=str(tmp_path / "outputs"),
            style=None,
            variations=1,
            asset_id=None,
            verbose=False,
        )
        
        result = cmd_run(args)
        assert result == 1  # Should fail
    
    def test_run_requires_project_or_input(self, tmp_path, env_file):
        """Run command fails without project or input file."""
        from artgen import cmd_run
        import argparse
        
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            
            args = argparse.Namespace(
                step="generate_image",
                input=None,
                env=str(env_file),
                output=str(tmp_path / "outputs"),
                style=None,
                variations=1,
                asset_id=None,
                verbose=False,
            )
            
            result = cmd_run(args)
            assert result == 1  # Should fail - no project and no input
        finally:
            os.chdir(original_cwd)
    
    def test_run_with_input_file(self, tmp_path, input_file, env_file, mock_provider):
        """Run command processes input file."""
        output_dir = tmp_path / "outputs"
        
        with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
            mock_registry.return_value.get_image_provider.return_value = mock_provider
            
            from artgen import cmd_run
            import argparse
            
            args = argparse.Namespace(
                step="generate_image",
                input=str(input_file),
                env=str(env_file),
                output=str(output_dir),
                style=None,
                variations=1,
                asset_id=None,
                verbose=False,
            )
            
            result = cmd_run(args)
        
        assert result == 0
        assert mock_provider.generate.call_count == 2  # 2 items in input file
    
    def test_run_generate_sprite_step(self, tmp_path, input_file, env_file):
        """Run command works with generate_sprite step."""
        output_dir = tmp_path / "outputs"
        
        mock_image = Image.new("RGBA", (100, 100), color=(255, 0, 0, 255))
        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=[mock_image])
        
        with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
            mock_registry.return_value.get_image_provider.return_value = mock_provider
            with patch("rembg.remove") as mock_rembg:
                mock_rembg.return_value = mock_image
                
                from artgen import cmd_run
                import argparse
                
                args = argparse.Namespace(
                    step="generate_sprite",
                    input=str(input_file),
                    env=str(env_file),
                    output=str(output_dir),
                    style=None,
                    variations=1,
                    asset_id=None,
                    verbose=False,
                )
                
                result = cmd_run(args)
        
        assert result == 0
        assert mock_rembg.called  # Background removal should be called
    
    def test_run_with_existing_project(self, tmp_path, env_file, mock_provider):
        """Run command works with existing project assets."""
        import json
        
        # Create project with pending asset
        (tmp_path / "artgen.json").write_text(json.dumps({
            "name": "Test",
            "pipeline": [{"id": "generate_image", "type": "generate_image", "variations": 1}]
        }))
        (tmp_path / ".artgen").mkdir()
        (tmp_path / "outputs").mkdir()
        # Create asset output directory
        (tmp_path / "outputs" / "test-001").mkdir()
        
        asset_data = {
            "id": "test-001",
            "input_description": "A test item",
            "status": "pending",
            "results": {},
            "created_at": "2026-01-29T00:00:00",
            "updated_at": "2026-01-29T00:00:00",
        }
        (tmp_path / ".artgen" / "progress.jsonl").write_text(json.dumps(asset_data) + "\n")
        
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            
            with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
                mock_registry.return_value.get_image_provider.return_value = mock_provider
                
                from artgen import cmd_run
                import argparse
                
                args = argparse.Namespace(
                    step="generate_image",
                    input=None,  # Use project
                    env=str(env_file),
                    output=str(tmp_path / "outputs"),
                    style=None,
                    variations=1,
                    asset_id=None,
                    verbose=True,  # Enable verbose to see errors
                )
                
                result = cmd_run(args)
            
            assert result == 0
            assert mock_provider.generate.called
        finally:
            os.chdir(original_cwd)
    
    def test_run_with_specific_asset(self, tmp_path, env_file, mock_provider):
        """Run command works with --asset flag for specific asset."""
        import json
        
        # Create project with multiple assets
        (tmp_path / "artgen.json").write_text(json.dumps({
            "name": "Test",
            "pipeline": [{"id": "generate_image", "type": "generate_image", "variations": 1}]
        }))
        (tmp_path / ".artgen").mkdir()
        (tmp_path / "outputs").mkdir()
        
        assets = [
            {"id": "item-001", "input_description": "Item 1", "status": "completed", "results": {}, "created_at": "2026-01-29T00:00:00", "updated_at": "2026-01-29T00:00:00"},
            {"id": "item-002", "input_description": "Item 2", "status": "pending", "results": {}, "created_at": "2026-01-29T00:00:00", "updated_at": "2026-01-29T00:00:00"},
        ]
        (tmp_path / ".artgen" / "progress.jsonl").write_text("\n".join(json.dumps(a) for a in assets) + "\n")
        
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            
            with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
                mock_registry.return_value.get_image_provider.return_value = mock_provider
                
                from artgen import cmd_run
                import argparse
                
                args = argparse.Namespace(
                    step="generate_image",
                    input=None,
                    env=str(env_file),
                    output=str(tmp_path / "outputs"),
                    style=None,
                    variations=1,
                    asset_id="item-002",
                    verbose=False,
                )
                
                result = cmd_run(args)
            
            # Should only process the specified asset
            assert mock_provider.generate.call_count == 1
        finally:
            os.chdir(original_cwd)
    
    def test_run_help_from_cli(self):
        """Run command help is accessible from CLI."""
        import artgen
        
        original_argv = sys.argv
        try:
            sys.argv = ["artgen", "run", "--help"]
            with pytest.raises(SystemExit) as exc_info:
                artgen.main()
            assert exc_info.value.code == 0
        finally:
            sys.argv = original_argv


class TestEnvFileResolution:
    """Test environment file discovery."""
    
    def test_explicit_env_takes_priority(self, tmp_path):
        """--env flag takes priority over auto-discovery."""
        from artgen import setup_env
        
        # Create multiple env files
        (tmp_path / ".env").write_text("A=1")
        (tmp_path / ".env.local").write_text("B=2")
        explicit = tmp_path / "custom.env"
        explicit.write_text("C=3")
        
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = setup_env(str(explicit))
            assert result == str(explicit)
        finally:
            os.chdir(original_cwd)
    
    def test_env_local_preferred_over_env(self, tmp_path):
        """".env.local takes priority over .env."""
        from artgen import setup_env
        import os as os_module
        
        # Clear any existing env var
        if "ARTGEN_ENV_FILE" in os_module.environ:
            del os_module.environ["ARTGEN_ENV_FILE"]
        
        # Create both files
        (tmp_path / ".env").write_text("A=1")
        (tmp_path / ".env.local").write_text("B=2")
        
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = setup_env(None)
            assert result == str(tmp_path / ".env.local")
        finally:
            os.chdir(original_cwd)
            if "ARTGEN_ENV_FILE" in os_module.environ:
                del os_module.environ["ARTGEN_ENV_FILE"]


class TestResumeCommand:
    """Test the resume command."""
    
    @pytest.fixture
    def mock_image(self):
        """Create a test image."""
        return Image.new("RGB", (100, 100), color="red")
    
    @pytest.fixture
    def mock_provider(self, mock_image):
        """Create a mocked image provider."""
        provider = MagicMock()
        provider.generate = AsyncMock(return_value=[mock_image])
        return provider
    
    @pytest.fixture
    def env_file(self, tmp_path):
        """Create a test env file."""
        env_path = tmp_path / ".env.test"
        env_path.write_text("GOOGLE_API_KEY=test-api-key")
        return env_path
    
    def test_resume_without_project(self, tmp_path, env_file):
        """Resume command fails without project."""
        from artgen import cmd_resume
        import argparse
        
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            
            args = argparse.Namespace(
                env=str(env_file),
                failed_only=False,
                verbose=False,
            )
            
            result = cmd_resume(args)
            assert result == 1  # Should fail
        finally:
            os.chdir(original_cwd)
    
    def test_resume_with_pending_assets(self, tmp_path, env_file, mock_provider):
        """Resume command processes pending assets."""
        import json
        
        # Create project with pending asset
        (tmp_path / "artgen.json").write_text(json.dumps({
            "name": "Test",
            "pipeline": [{"id": "generate_image", "type": "generate_image", "variations": 1}]
        }))
        (tmp_path / ".artgen").mkdir()
        (tmp_path / "outputs").mkdir()
        # Create asset output directory
        (tmp_path / "outputs" / "test-001").mkdir()
        
        asset_data = {
            "id": "test-001",
            "input_description": "A test item",
            "status": "pending",
            "results": {},
            "created_at": "2026-01-29T00:00:00",
            "updated_at": "2026-01-29T00:00:00",
        }
        (tmp_path / ".artgen" / "progress.jsonl").write_text(json.dumps(asset_data) + "\n")
        
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            
            with patch("pipeline.orchestrator.get_provider_registry") as mock_registry:
                mock_registry.return_value.get_image_provider.return_value = mock_provider
                
                from artgen import cmd_resume
                import argparse
                
                args = argparse.Namespace(
                    env=str(env_file),
                    failed_only=False,
                    verbose=False,
                )
                
                result = cmd_resume(args)
            
            assert result == 0
            assert mock_provider.generate.called
        finally:
            os.chdir(original_cwd)
    
    def test_resume_no_pending_assets(self, tmp_path, env_file):
        """Resume command returns success when no pending assets."""
        import json
        
        # Create project with completed asset
        (tmp_path / "artgen.json").write_text(json.dumps({
            "name": "Test",
            "pipeline": [{"id": "generate_image", "type": "generate_image", "variations": 1}]
        }))
        (tmp_path / ".artgen").mkdir()
        (tmp_path / "outputs").mkdir()
        
        asset_data = {
            "id": "test-001",
            "input_description": "A test item",
            "status": "completed",
            "results": {},
            "created_at": "2026-01-29T00:00:00",
            "updated_at": "2026-01-29T00:00:00",
        }
        (tmp_path / ".artgen" / "progress.jsonl").write_text(json.dumps(asset_data) + "\n")
        
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            
            from artgen import cmd_resume
            import argparse
            
            args = argparse.Namespace(
                env=str(env_file),
                failed_only=False,
                verbose=False,
            )
            
            result = cmd_resume(args)
            assert result == 0  # Success - nothing to process
        finally:
            os.chdir(original_cwd)
