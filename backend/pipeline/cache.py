"""
Caching and Checkpointing for Pipeline Execution.

Provides:
  - Step output caching (skip completed steps)
  - Per-asset skip_existing (only process new assets)
  - Pipeline state persistence
  - Cache invalidation
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


class CacheManager:
    """
    Manages caching and checkpointing for pipeline execution.
    
    Cache behavior:
      - cache: true - Load from cache if exists, skip step entirely
      - cache: false - Always run the step
      - cache: skip_existing - For per-asset steps, skip assets with existing output
    """
    
    def __init__(self, state_dir: Path):
        """
        Initialize the cache manager.
        
        Args:
            state_dir: Directory for storing state files
        """
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Track pipeline state
        self._pipeline_hash: str | None = None
        self._step_states: dict[str, dict] = {}
        
        # Load existing state
        self._load_state()
    
    def _load_state(self) -> None:
        """Load pipeline state from disk."""
        state_file = self.state_dir / "pipeline_state.json"
        
        if state_file.exists():
            try:
                with open(state_file, "r") as f:
                    data = json.load(f)
                    self._pipeline_hash = data.get("pipeline_hash")
                    self._step_states = data.get("steps", {})
            except (json.JSONDecodeError, IOError):
                # Corrupted state, start fresh
                self._pipeline_hash = None
                self._step_states = {}
    
    def _save_state(self) -> None:
        """Save pipeline state to disk."""
        state_file = self.state_dir / "pipeline_state.json"
        
        data = {
            "pipeline_hash": self._pipeline_hash,
            "updated_at": datetime.utcnow().isoformat(),
            "steps": self._step_states,
        }
        
        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)
    
    def check_pipeline_changed(self, pipeline_yaml: str) -> bool:
        """
        Check if the pipeline definition has changed.
        
        Args:
            pipeline_yaml: The pipeline YAML content
            
        Returns:
            True if pipeline changed (cache may be invalid)
        """
        current_hash = hashlib.sha256(pipeline_yaml.encode()).hexdigest()[:16]
        
        if self._pipeline_hash is None:
            self._pipeline_hash = current_hash
            self._save_state()
            return False  # First run, no change
        
        if current_hash != self._pipeline_hash:
            self._pipeline_hash = current_hash
            self._save_state()
            return True
        
        return False
    
    def is_step_cached(
        self,
        step_id: str,
        asset_id: str | None = None,
    ) -> bool:
        """
        Check if a step's output is cached.
        
        Args:
            step_id: The step ID
            asset_id: Optional asset ID for per-asset steps
            
        Returns:
            True if cached output exists
        """
        if asset_id:
            cache_key = f"{step_id}:{asset_id}"
        else:
            cache_key = step_id
        
        if cache_key not in self._step_states:
            return False
        
        state = self._step_states[cache_key]
        
        # Check if output file still exists
        if "output_path" in state:
            output_path = self.state_dir / state["output_path"]
            if not output_path.exists():
                return False
        
        return state.get("completed", False)
    
    def get_cached_output(
        self,
        step_id: str,
        asset_id: str | None = None,
    ) -> Any | None:
        """
        Get cached output for a step.
        
        Args:
            step_id: The step ID
            asset_id: Optional asset ID
            
        Returns:
            Cached output data or None
        """
        if asset_id:
            cache_key = f"{step_id}:{asset_id}"
        else:
            cache_key = step_id
        
        if cache_key not in self._step_states:
            return None
        
        state = self._step_states[cache_key]
        
        # Try to load from output file
        if "output_path" in state:
            output_path = self.state_dir / state["output_path"]
            if output_path.exists():
                try:
                    with open(output_path, "r") as f:
                        data = json.load(f)
                        return data.get("data")
                except (json.JSONDecodeError, IOError):
                    pass
        
        # Return inline cached data
        return state.get("output")
    
    def cache_step_output(
        self,
        step_id: str,
        output: Any,
        asset_id: str | None = None,
        output_paths: list[Path] | None = None,
        prompt: str | None = None,
        cost_usd: float = 0.0,
        tokens_used: dict[str, int] | None = None,
    ) -> None:
        """
        Cache a step's output.
        
        Args:
            step_id: The step ID
            output: The output data
            asset_id: Optional asset ID
            output_paths: List of output file paths
            prompt: Optional prompt used to generate this output
            cost_usd: Cost of this step in USD
            tokens_used: Token usage breakdown (prompt_tokens, completion_tokens, total_tokens)
        """
        if asset_id:
            cache_key = f"{step_id}:{asset_id}"
            output_file = f"{step_id}/{asset_id}/output.json"
        else:
            cache_key = step_id
            output_file = f"{step_id}/output.json"
        
        # Ensure directory exists
        (self.state_dir / output_file).parent.mkdir(parents=True, exist_ok=True)
        
        # Save output to file
        output_data = {
            "step_id": step_id,
            "asset_id": asset_id,
            "timestamp": datetime.utcnow().isoformat(),
            "data": output,
        }
        
        # Include prompt if provided
        if prompt:
            output_data["prompt"] = prompt
        
        # Include cost tracking if available
        if cost_usd > 0:
            output_data["cost_usd"] = cost_usd
        if tokens_used:
            output_data["tokens_used"] = tokens_used
        
        with open(self.state_dir / output_file, "w") as f:
            json.dump(output_data, f, indent=2, default=str)
        
        # Update state
        self._step_states[cache_key] = {
            "completed": True,
            "completed_at": datetime.utcnow().isoformat(),
            "output_path": output_file,
            "output_files": [str(p) for p in (output_paths or [])],
            "cost_usd": cost_usd,
        }
        
        self._save_state()
    
    def invalidate_step(
        self,
        step_id: str,
        asset_id: str | None = None,
    ) -> None:
        """
        Invalidate cached output for a step.
        
        Args:
            step_id: The step ID
            asset_id: Optional asset ID
        """
        if asset_id:
            cache_key = f"{step_id}:{asset_id}"
        else:
            cache_key = step_id
        
        if cache_key in self._step_states:
            del self._step_states[cache_key]
            self._save_state()
    
    def invalidate_all(self) -> None:
        """Invalidate all cached data."""
        self._step_states = {}
        self._pipeline_hash = None
        self._save_state()
    
    def get_completed_assets(self, step_id: str) -> set[str]:
        """
        Get set of asset IDs that have completed a step.
        
        Args:
            step_id: The step ID
            
        Returns:
            Set of completed asset IDs
        """
        completed = set()
        prefix = f"{step_id}:"
        
        for key, state in self._step_states.items():
            if key.startswith(prefix) and state.get("completed"):
                asset_id = key[len(prefix):]
                completed.add(asset_id)
        
        return completed
    
    def get_pending_assets(
        self,
        step_id: str,
        all_asset_ids: list[str],
    ) -> list[str]:
        """
        Get list of asset IDs that haven't completed a step.
        
        Args:
            step_id: The step ID
            all_asset_ids: All asset IDs
            
        Returns:
            List of pending asset IDs
        """
        completed = self.get_completed_assets(step_id)
        return [aid for aid in all_asset_ids if aid not in completed]


def should_skip_step(
    cache_manager: CacheManager,
    step_id: str,
    cache_setting: bool | str,
    asset_id: str | None = None,
) -> bool:
    """
    Determine if a step should be skipped based on cache settings.
    
    Args:
        cache_manager: The cache manager
        step_id: The step ID
        cache_setting: The step's cache setting
        asset_id: Optional asset ID
        
    Returns:
        True if step should be skipped
    """
    if cache_setting is False:
        return False
    
    if cache_setting is True or cache_setting == "skip_existing":
        return cache_manager.is_step_cached(step_id, asset_id)
    
    return False
