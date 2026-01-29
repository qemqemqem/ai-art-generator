"""Test fixtures and configuration."""

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def anyio_backend():
    """Use asyncio for async tests."""
    return "asyncio"


@pytest_asyncio.fixture
async def client(tmp_path):
    """Create a test client with an isolated temp project directory."""
    # Import here to avoid circular import issues
    import app.main as main_module
    from app.main import app
    
    # Create temp project dir
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    
    # Save original cwd and project state
    original_cwd = os.getcwd()
    original_project = main_module._project
    
    # Reset global state and change to temp dir
    main_module._project = None
    os.chdir(project_dir)
    
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        # Restore original state
        main_module._project = original_project
        os.chdir(original_cwd)


@pytest_asyncio.fixture
async def project(tmp_path):
    """Create a standalone test project (not connected to API)."""
    from pipeline import Project
    
    project_dir = tmp_path / "standalone_project"
    project_dir.mkdir()
    
    original_cwd = os.getcwd()
    os.chdir(project_dir)
    
    try:
        proj = await Project.init(project_dir)
        yield proj
    finally:
        os.chdir(original_cwd)


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "live: tests that hit real AI APIs (cost money)")
    config.addinivalue_line("markers", "slow: tests that take longer to run")
