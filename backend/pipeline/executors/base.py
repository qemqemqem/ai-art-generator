"""
Base Step Executor.

Abstract base class for all step executors. Provides common functionality
for caching, output paths, and variation handling.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ExecutorContext:
    """
    Context passed to step executors.
    
    Contains all the information an executor needs to run.
    """
    # Pipeline info
    pipeline_name: str
    base_path: Path
    state_dir: Path
    
    # Current context and step outputs
    context: dict[str, Any]
    step_outputs: dict[str, Any]
    
    # Current asset (for per-asset steps)
    asset: dict[str, Any] | None = None
    asset_index: int = 0
    total_assets: int = 0
    
    # Variation tracking
    variation_index: int = 0
    
    # Provider registry
    providers: Any = None


@dataclass
class StepResult:
    """
    Result of executing a step.
    """
    success: bool
    output: Any = None
    variations: list[Any] = field(default_factory=list)
    selected_index: int | None = None
    error: str | None = None
    duration_ms: int = 0
    cached: bool = False
    
    # File paths produced
    output_paths: list[Path] = field(default_factory=list)


class StepExecutor(ABC):
    """
    Abstract base class for step executors.
    
    Each step type (research, generate_image, etc.) has a corresponding
    executor subclass that implements the execute() method.
    """
    
    # Override in subclasses
    step_type: str = "base"
    
    def __init__(self):
        pass
    
    @abstractmethod
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute the step.
        
        Args:
            config: Step configuration from the pipeline YAML
            ctx: Execution context
            
        Returns:
            StepResult with output and metadata
        """
        pass
    
    def get_output_path(
        self,
        ctx: ExecutorContext,
        step_id: str,
        filename: str | None = None,
        variation: int | None = None,
    ) -> Path:
        """
        Get the output path for a step's artifact.
        
        Args:
            ctx: Execution context
            step_id: The step ID
            filename: Optional specific filename
            variation: Optional variation number
            
        Returns:
            Full path for the output file
        """
        if ctx.asset:
            # Per-asset step
            asset_id = ctx.asset.get("id", f"asset-{ctx.asset_index:03d}")
            base = ctx.state_dir / step_id / asset_id
        else:
            # Global step
            base = ctx.state_dir / step_id
        
        base.mkdir(parents=True, exist_ok=True)
        
        if filename:
            return base / filename
        elif variation is not None:
            return base / f"v{variation + 1}.json"
        else:
            return base / "output.json"
    
    def get_image_output_path(
        self,
        ctx: ExecutorContext,
        step_id: str,
        variation: int,
        extension: str = "png",
    ) -> Path:
        """
        Get the output path for an image artifact.
        
        Args:
            ctx: Execution context
            step_id: The step ID
            variation: Variation number (0-indexed)
            extension: File extension
            
        Returns:
            Full path for the image file
        """
        if ctx.asset:
            asset_id = ctx.asset.get("id", f"asset-{ctx.asset_index:03d}")
            base = ctx.state_dir / step_id / asset_id
        else:
            base = ctx.state_dir / step_id
        
        base.mkdir(parents=True, exist_ok=True)
        return base / f"v{variation + 1}.{extension}"
    
    def save_json_output(
        self,
        ctx: ExecutorContext,
        step_id: str,
        data: Any,
        filename: str | None = None,
    ) -> Path:
        """
        Save JSON output for a step.
        
        Args:
            ctx: Execution context
            step_id: The step ID
            data: Data to save
            filename: Optional specific filename
            
        Returns:
            Path to the saved file
        """
        import json
        
        path = self.get_output_path(ctx, step_id, filename)
        
        output = {
            "step_id": step_id,
            "timestamp": datetime.utcnow().isoformat(),
            "asset_id": ctx.asset.get("id") if ctx.asset else None,
            "data": data,
        }
        
        with open(path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        
        return path
    
    def load_cached_output(
        self,
        ctx: ExecutorContext,
        step_id: str,
        filename: str | None = None,
    ) -> Any | None:
        """
        Load cached output for a step.
        
        Args:
            ctx: Execution context
            step_id: The step ID
            filename: Optional specific filename
            
        Returns:
            Cached data or None if not found
        """
        import json
        
        path = self.get_output_path(ctx, step_id, filename)
        
        if not path.exists():
            return None
        
        with open(path, "r") as f:
            data = json.load(f)
        
        return data.get("data")
