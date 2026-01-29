"""Tests for API endpoints - uses mocked providers where possible."""

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.anyio
class TestHealthEndpoints:
    """Test health and info endpoints."""
    
    async def test_root(self, client: AsyncClient):
        """Root endpoint returns app info."""
        response = await client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "AI Art Generator"
        assert data["status"] == "running"
        assert "project" in data
    
    async def test_health(self, client: AsyncClient):
        """Health endpoint returns healthy."""
        response = await client.get("/health")
        
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    async def test_providers(self, client: AsyncClient):
        """Providers endpoint lists available providers."""
        response = await client.get("/providers")
        
        assert response.status_code == 200
        data = response.json()
        assert "image" in data
        assert "text" in data
        assert "research" in data
        assert "gemini" in data["image"]


@pytest.mark.anyio
class TestProjectEndpoints:
    """Test project management endpoints."""
    
    async def test_get_project(self, client: AsyncClient):
        """Get current project info."""
        response = await client.get("/project")
        
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "config" in data
        assert "asset_count" in data
    
    async def test_update_config(self, client: AsyncClient):
        """Update project configuration."""
        new_config = {
            "name": "Test Project",
            "description": "A test project",
            "style": {
                "global_prompt_prefix": "fantasy art",
                "global_prompt_suffix": "detailed",
                "negative_prompt": "",
                "aspect_ratio": "1:1",
                "image_size": "1K",
            },
            "pipeline": [],
            "default_image_provider": "gemini",
            "default_text_provider": "gemini",
            "settings": {},
        }
        
        response = await client.put("/project/config", json=new_config)
        
        assert response.status_code == 200
        data = response.json()
        assert data["config"]["name"] == "Test Project"
        assert data["config"]["style"]["global_prompt_prefix"] == "fantasy art"


@pytest.mark.anyio
class TestAssetEndpoints:
    """Test asset management endpoints."""
    
    async def test_list_assets_empty(self, client: AsyncClient):
        """List assets when none exist."""
        response = await client.get("/assets")
        
        assert response.status_code == 200
        assert response.json()["assets"] == []
    
    async def test_add_assets(self, client: AsyncClient):
        """Add assets from list."""
        items = [
            {"description": "A wise owl wizard"},
            {"description": "Fire-breathing dragon"},
        ]
        
        response = await client.post("/assets", json=items)
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["assets"]) == 2
        assert data["assets"][0]["input_description"] == "A wise owl wizard"
        assert data["assets"][0]["status"] == "pending"
    
    async def test_upload_text_input(self, client: AsyncClient):
        """Upload text input."""
        response = await client.post(
            "/assets/upload",
            json={
                "content": "Wise owl wizard\nFire-breathing dragon",
                "format": "text",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["assets"]) == 2
    
    async def test_upload_json_input(self, client: AsyncClient):
        """Upload JSON input."""
        response = await client.post(
            "/assets/upload",
            json={
                "content": '[{"description": "A wise owl wizard"}]',
                "format": "json",
            },
        )
        
        assert response.status_code == 200
        assert len(response.json()["assets"]) == 1
    
    async def test_get_asset(self, client: AsyncClient):
        """Get a specific asset."""
        # First create an asset
        await client.post(
            "/assets",
            json=[{"description": "Test asset"}],
        )
        
        # Then get it
        response = await client.get("/assets/asset-001")
        
        assert response.status_code == 200
        assert response.json()["input_description"] == "Test asset"
    
    async def test_get_asset_not_found(self, client: AsyncClient):
        """Get nonexistent asset returns 404."""
        response = await client.get("/assets/nonexistent")
        
        assert response.status_code == 404


@pytest.mark.anyio
class TestQueueEndpoints:
    """Test approval queue endpoints."""
    
    async def test_queue_empty(self, client: AsyncClient):
        """Empty queue when no assets awaiting approval."""
        response = await client.get("/queue")
        
        assert response.status_code == 200
        assert response.json()["queue"] == []


@pytest.mark.anyio
class TestFileServing:
    """Test file serving endpoint."""
    
    async def test_file_not_found(self, client: AsyncClient):
        """Nonexistent file returns 404."""
        response = await client.get("/files/nonexistent.png")
        
        assert response.status_code == 404
