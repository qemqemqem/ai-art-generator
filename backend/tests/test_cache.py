"""Tests for the caching system."""

import json
import tempfile
from pathlib import Path

import pytest

from pipeline.cache import CacheManager, should_skip_step


class TestCacheManager:
    """Tests for the CacheManager class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.state_dir = Path(self.temp_dir)
        self.cache = CacheManager(self.state_dir)
    
    def test_initial_state(self):
        """Test that cache starts empty."""
        assert not self.cache.is_step_cached("some_step")
        assert self.cache.get_cached_output("some_step") is None
    
    def test_cache_global_step(self):
        """Test caching a global step's output."""
        self.cache.cache_step_output(
            "research",
            {"content": "Test research result"},
        )
        
        assert self.cache.is_step_cached("research")
        
        output = self.cache.get_cached_output("research")
        assert output["content"] == "Test research result"
    
    def test_cache_per_asset_step(self):
        """Test caching a per-asset step's output."""
        self.cache.cache_step_output(
            "generate",
            {"path": "images/archer/v1.png"},
            asset_id="archer",
        )
        
        assert self.cache.is_step_cached("generate", "archer")
        assert not self.cache.is_step_cached("generate", "knight")
        
        output = self.cache.get_cached_output("generate", "archer")
        assert output["path"] == "images/archer/v1.png"
    
    def test_get_completed_assets(self):
        """Test getting list of completed assets for a step."""
        self.cache.cache_step_output("generate", {}, asset_id="archer")
        self.cache.cache_step_output("generate", {}, asset_id="knight")
        self.cache.cache_step_output("generate", {}, asset_id="wizard")
        
        completed = self.cache.get_completed_assets("generate")
        
        assert "archer" in completed
        assert "knight" in completed
        assert "wizard" in completed
        assert len(completed) == 3
    
    def test_get_pending_assets(self):
        """Test getting list of pending assets for a step."""
        self.cache.cache_step_output("generate", {}, asset_id="archer")
        self.cache.cache_step_output("generate", {}, asset_id="knight")
        
        all_ids = ["archer", "knight", "wizard", "healer"]
        pending = self.cache.get_pending_assets("generate", all_ids)
        
        assert "wizard" in pending
        assert "healer" in pending
        assert "archer" not in pending
        assert len(pending) == 2
    
    def test_invalidate_step(self):
        """Test invalidating a step's cache."""
        self.cache.cache_step_output("research", {"data": "test"})
        assert self.cache.is_step_cached("research")
        
        self.cache.invalidate_step("research")
        assert not self.cache.is_step_cached("research")
    
    def test_invalidate_per_asset(self):
        """Test invalidating a specific asset's cache."""
        self.cache.cache_step_output("generate", {}, asset_id="archer")
        self.cache.cache_step_output("generate", {}, asset_id="knight")
        
        self.cache.invalidate_step("generate", "archer")
        
        assert not self.cache.is_step_cached("generate", "archer")
        assert self.cache.is_step_cached("generate", "knight")
    
    def test_invalidate_all(self):
        """Test invalidating all cached data."""
        self.cache.cache_step_output("research", {})
        self.cache.cache_step_output("generate", {}, asset_id="archer")
        
        self.cache.invalidate_all()
        
        assert not self.cache.is_step_cached("research")
        assert not self.cache.is_step_cached("generate", "archer")
    
    def test_pipeline_hash_tracking(self):
        """Test that pipeline hash changes are detected."""
        pipeline_v1 = "name: test\nsteps: []"
        pipeline_v2 = "name: test\nsteps: []\ndescription: updated"
        
        # First run - no change
        assert not self.cache.check_pipeline_changed(pipeline_v1)
        
        # Same content - no change
        assert not self.cache.check_pipeline_changed(pipeline_v1)
        
        # Different content - change detected
        assert self.cache.check_pipeline_changed(pipeline_v2)
    
    def test_persistence(self):
        """Test that cache persists across instances."""
        # Cache some data
        self.cache.cache_step_output("research", {"content": "persisted"})
        
        # Create new cache instance with same directory
        new_cache = CacheManager(self.state_dir)
        
        assert new_cache.is_step_cached("research")
        output = new_cache.get_cached_output("research")
        assert output["content"] == "persisted"


class TestShouldSkipStep:
    """Tests for the should_skip_step function."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheManager(Path(self.temp_dir))
    
    def test_cache_false(self):
        """Test that cache=False never skips."""
        self.cache.cache_step_output("step", {})
        
        result = should_skip_step(self.cache, "step", False)
        
        assert result is False
    
    def test_cache_true_with_cache(self):
        """Test that cache=True skips when cached."""
        self.cache.cache_step_output("step", {})
        
        result = should_skip_step(self.cache, "step", True)
        
        assert result is True
    
    def test_cache_true_without_cache(self):
        """Test that cache=True doesn't skip when not cached."""
        result = should_skip_step(self.cache, "step", True)
        
        assert result is False
    
    def test_skip_existing_with_asset(self):
        """Test skip_existing with per-asset steps."""
        self.cache.cache_step_output("step", {}, asset_id="archer")
        
        result = should_skip_step(self.cache, "step", "skip_existing", "archer")
        assert result is True
        
        result = should_skip_step(self.cache, "step", "skip_existing", "knight")
        assert result is False
