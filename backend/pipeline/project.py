"""Project management for AI art generation."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiofiles

from app.models import (
    Asset,
    AssetStatus,
    InputItem,
    ProjectConfig,
    StepResult,
    StyleConfig,
    PipelineStep,
    StepType,
)


class Project:
    """A generation project rooted in the current working directory."""
    
    def __init__(self, path: Optional[Path] = None, config: Optional[ProjectConfig] = None):
        """Initialize a project.
        
        Args:
            path: Path to the project directory (defaults to cwd)
            config: Optional project configuration (loaded from disk if not provided)
        """
        self.path = path or Path.cwd()
        self._config = config
        self._assets: dict[str, Asset] = {}
        
    @property
    def config(self) -> ProjectConfig:
        """Get the project configuration."""
        if self._config is None:
            self._config = self._load_config()
        return self._config
    
    @property
    def outputs_dir(self) -> Path:
        return self.path / "outputs"
    
    @property
    def state_dir(self) -> Path:
        return self.path / ".artgen"
    
    @property
    def cache_dir(self) -> Path:
        return self.path / ".artgen" / "cache"
    
    def _load_config(self) -> ProjectConfig:
        """Load configuration from disk."""
        config_path = self.path / "artgen.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    return ProjectConfig(**data)
        return ProjectConfig(name=self.path.name)
    
    async def save_config(self):
        """Save configuration to disk."""
        config_path = self.path / "artgen.json"
        async with aiofiles.open(config_path, "w") as f:
            await f.write(self.config.model_dump_json(indent=2))
    
    def ensure_directories(self):
        """Ensure all project directories exist."""
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    async def load_assets(self) -> dict[str, Asset]:
        """Load all assets from state."""
        progress_file = self.state_dir / "progress.jsonl"
        if not progress_file.exists():
            return {}
        
        # Read all lines and keep the latest version of each asset
        assets = {}
        async with aiofiles.open(progress_file, "r") as f:
            async for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    asset = Asset(**data)
                    assets[asset.id] = asset
        
        self._assets = assets
        return assets
    
    async def save_asset(self, asset: Asset):
        """Save or update an asset to state."""
        asset.updated_at = datetime.utcnow()
        self._assets[asset.id] = asset
        
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Append to progress file
        progress_file = self.state_dir / "progress.jsonl"
        async with aiofiles.open(progress_file, "a") as f:
            await f.write(asset.model_dump_json() + "\n")
    
    async def create_asset(self, item: InputItem) -> Asset:
        """Create a new asset from an input item."""
        asset = Asset(
            id=item.id or f"asset-{len(self._assets)+1:03d}",
            input_description=item.description,
            input_metadata=item.metadata,
        )
        
        # Create output directory for this asset
        asset_dir = self.outputs_dir / asset.id
        asset_dir.mkdir(parents=True, exist_ok=True)
        
        await self.save_asset(asset)
        return asset
    
    def get_asset(self, asset_id: str) -> Optional[Asset]:
        """Get an asset by ID."""
        return self._assets.get(asset_id)
    
    def get_asset_dir(self, asset_id: str) -> Path:
        """Get the output directory for an asset."""
        return self.outputs_dir / asset_id
    
    def get_pending_assets(self) -> list[Asset]:
        """Get all assets that are pending processing."""
        return [a for a in self._assets.values() if a.status == AssetStatus.PENDING]
    
    def get_awaiting_approval(self) -> list[Asset]:
        """Get all assets awaiting human approval."""
        return [a for a in self._assets.values() if a.status == AssetStatus.AWAITING_APPROVAL]
    
    def get_queue(self) -> list[tuple[Asset, str, StepResult]]:
        """Get the approval queue: (asset, step_id, step_result)."""
        queue = []
        for asset in self._assets.values():
            if asset.status == AssetStatus.AWAITING_APPROVAL:
                for step_id, result in asset.results.items():
                    if result.status == AssetStatus.AWAITING_APPROVAL:
                        queue.append((asset, step_id, result))
        return queue
    
    @classmethod
    async def init(cls, path: Optional[Path] = None, config: Optional[ProjectConfig] = None) -> "Project":
        """Initialize a new project in the given directory.
        
        Args:
            path: Path to initialize (defaults to cwd)
            config: Optional project configuration
            
        Returns:
            The initialized Project
        """
        project = cls(path, config)
        project.ensure_directories()
        await project.save_config()
        return project
    
    @classmethod
    async def load(cls, path: Optional[Path] = None) -> "Project":
        """Load an existing project from the given directory.
        
        Args:
            path: Path to load from (defaults to cwd)
            
        Returns:
            The loaded Project
        """
        project = cls(path)
        await project.load_assets()
        return project
    
    @classmethod
    def exists(cls, path: Optional[Path] = None) -> bool:
        """Check if a project exists at the given path."""
        project_path = path or Path.cwd()
        return (project_path / "artgen.json").exists()


# Default pipeline templates
DEFAULT_SIMPLE_PIPELINE = [
    PipelineStep(
        id="generate_image",
        type=StepType.GENERATE_IMAGE,
        variations=4,
        requires_approval=True,
    ),
]

DEFAULT_FULL_PIPELINE = [
    PipelineStep(
        id="research",
        type=StepType.RESEARCH,
        requires_approval=False,
    ),
    PipelineStep(
        id="generate_name",
        type=StepType.GENERATE_NAME,
        requires_approval=True,
    ),
    PipelineStep(
        id="generate_portrait",
        type=StepType.GENERATE_IMAGE,
        variations=4,
        requires_approval=True,
        config={"image_type": "portrait"},
    ),
    PipelineStep(
        id="generate_sprite",
        type=StepType.GENERATE_SPRITE,
        variations=2,
        requires_approval=True,
        parallel_with=["generate_portrait"],
    ),
    PipelineStep(
        id="generate_description",
        type=StepType.GENERATE_TEXT,
        requires_approval=True,
        parallel_with=["generate_portrait"],
    ),
]
