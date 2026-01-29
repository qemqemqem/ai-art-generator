"""Queue manager for interactive approval workflow.

Handles the async generation queue and approval workflow for interactive mode.
"""

import asyncio
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models import Asset, AssetStatus, PipelineStep, GeneratedArtifact


class ApprovalType(str, Enum):
    """How the user approves this item."""
    CHOOSE_ONE = "choose_one"  # Select 1 from N options
    ACCEPT_REJECT = "accept_reject"  # Yes/no on each option


class GeneratedOption(BaseModel):
    """A single generated option for approval."""
    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    type: str  # "image" or "text"
    
    # For images
    image_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    image_data_url: Optional[str] = None  # base64 for quick display
    
    # For text
    text_content: Optional[str] = None
    
    # Generation info
    prompt_used: Optional[str] = None
    generation_params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ApprovalItem(BaseModel):
    """An item waiting for user approval."""
    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    asset_id: str
    asset_description: str
    step_id: str
    step_name: str
    step_index: int
    total_steps: int
    
    approval_type: ApprovalType
    options: list[GeneratedOption] = Field(default_factory=list)
    
    # Context from previous steps
    context: dict[str, Any] = Field(default_factory=dict)
    
    # Status tracking
    attempt: int = 1
    max_attempts: int = 10
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GeneratingItem(BaseModel):
    """An item currently being generated."""
    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    asset_id: str
    asset_description: str
    step_id: str
    step_name: str
    progress: float = 0.0  # 0-100
    started_at: datetime = Field(default_factory=datetime.utcnow)


class QueueStatus(BaseModel):
    """Overall status of the generation queue."""
    total_assets: int = 0
    completed_assets: int = 0
    failed_assets: int = 0
    
    awaiting_approval: int = 0
    currently_generating: int = 0
    pending: int = 0
    
    is_running: bool = False
    is_paused: bool = False


class ApprovalDecision(BaseModel):
    """User's decision on an approval item."""
    item_id: str
    approved: bool
    selected_option_id: Optional[str] = None  # For choose_one
    regenerate: bool = False  # Request more options


class QueueManager:
    """Manages the interactive approval queue.
    
    This is the central coordinator for interactive mode. It:
    - Tracks items awaiting approval
    - Tracks items being generated
    - Manages the generation worker pool
    - Provides real-time status updates
    """
    
    def __init__(self):
        # Approval queue (items waiting for user)
        self._approval_queue: dict[str, ApprovalItem] = {}
        
        # Items being generated
        self._generating: dict[str, GeneratingItem] = {}
        
        # Completed items (for history)
        self._completed: list[str] = []
        
        # Assets in the pipeline
        self._assets: dict[str, Asset] = {}
        
        # Pending assets (not yet started)
        self._pending_asset_ids: list[str] = []
        
        # Worker control
        self._running = False
        self._paused = False
        self._worker_task: Optional[asyncio.Task] = None
        self._max_concurrent = 3  # Max simultaneous generations
        
        # Callbacks for WebSocket notifications
        self._on_new_approval: Optional[Callable[[ApprovalItem], None]] = None
        self._on_status_update: Optional[Callable[[QueueStatus], None]] = None
        self._on_progress: Optional[Callable[[str, str, float], None]] = None
    
    def set_callbacks(
        self,
        on_new_approval: Optional[Callable[[ApprovalItem], None]] = None,
        on_status_update: Optional[Callable[[QueueStatus], None]] = None,
        on_progress: Optional[Callable[[str, str, float], None]] = None,
    ):
        """Set callback functions for real-time updates."""
        self._on_new_approval = on_new_approval
        self._on_status_update = on_status_update
        self._on_progress = on_progress
    
    def get_status(self) -> QueueStatus:
        """Get current queue status."""
        total = len(self._assets)
        completed = len([a for a in self._assets.values() if a.status == AssetStatus.COMPLETED])
        failed = len([a for a in self._assets.values() if a.status == AssetStatus.FAILED])
        
        return QueueStatus(
            total_assets=total,
            completed_assets=completed,
            failed_assets=failed,
            awaiting_approval=len(self._approval_queue),
            currently_generating=len(self._generating),
            pending=len(self._pending_asset_ids),
            is_running=self._running,
            is_paused=self._paused,
        )
    
    def add_assets(self, assets: list[Asset]):
        """Add assets to the queue."""
        for asset in assets:
            self._assets[asset.id] = asset
            if asset.status == AssetStatus.PENDING:
                self._pending_asset_ids.append(asset.id)
        
        self._notify_status()
    
    def get_next_approval(self) -> Optional[ApprovalItem]:
        """Get the next item needing approval."""
        if not self._approval_queue:
            return None
        
        # Return the oldest item
        oldest_id = min(
            self._approval_queue.keys(),
            key=lambda k: self._approval_queue[k].created_at
        )
        return self._approval_queue[oldest_id]
    
    def get_all_approvals(self) -> list[ApprovalItem]:
        """Get all items awaiting approval."""
        return sorted(
            self._approval_queue.values(),
            key=lambda x: x.created_at
        )
    
    def get_generating_items(self) -> list[GeneratingItem]:
        """Get items currently being generated."""
        return list(self._generating.values())
    
    def add_approval_item(self, item: ApprovalItem):
        """Add an item to the approval queue."""
        self._approval_queue[item.id] = item
        
        if self._on_new_approval:
            self._on_new_approval(item)
        
        self._notify_status()
    
    def add_option_to_item(self, item_id: str, option: GeneratedOption):
        """Add a generated option to an existing approval item."""
        if item_id in self._approval_queue:
            self._approval_queue[item_id].options.append(option)
    
    async def submit_decision(self, decision: ApprovalDecision) -> dict[str, Any]:
        """Process user's approval decision."""
        if decision.item_id not in self._approval_queue:
            return {"error": f"Item not found: {decision.item_id}"}
        
        item = self._approval_queue[decision.item_id]
        asset = self._assets.get(item.asset_id)
        
        if decision.regenerate:
            # User wants more options
            item.attempt += 1
            if item.attempt > item.max_attempts:
                # Max attempts reached, mark as skipped
                del self._approval_queue[decision.item_id]
                if asset:
                    asset.status = AssetStatus.FAILED
                return {"status": "max_attempts_reached", "skipped": True}
            
            # Clear options and re-queue for generation
            item.options = []
            return {"status": "regenerating", "attempt": item.attempt}
        
        if decision.approved:
            # Find selected option
            selected = None
            if decision.selected_option_id:
                for opt in item.options:
                    if opt.id == decision.selected_option_id:
                        selected = opt
                        break
            elif item.options:
                # Default to first option if none specified
                selected = item.options[0]
            
            # Remove from approval queue
            del self._approval_queue[decision.item_id]
            self._completed.append(decision.item_id)
            
            self._notify_status()
            
            return {
                "status": "approved",
                "selected": selected.model_dump() if selected else None,
                "asset_id": item.asset_id,
                "step_id": item.step_id,
            }
        else:
            # Rejected - regenerate
            item.attempt += 1
            item.options = []
            return {"status": "rejected_regenerating", "attempt": item.attempt}
    
    def skip_item(self, item_id: str) -> dict[str, Any]:
        """Skip an approval item."""
        if item_id not in self._approval_queue:
            return {"error": f"Item not found: {item_id}"}
        
        item = self._approval_queue[item_id]
        del self._approval_queue[item_id]
        
        asset = self._assets.get(item.asset_id)
        if asset:
            asset.status = AssetStatus.FAILED
        
        self._notify_status()
        return {"status": "skipped", "asset_id": item.asset_id}
    
    def start_generating(self, asset_id: str, step_id: str, step_name: str) -> str:
        """Mark that we're starting to generate something."""
        item = GeneratingItem(
            asset_id=asset_id,
            asset_description=self._assets.get(asset_id, Asset(id="", input_description="")).input_description,
            step_id=step_id,
            step_name=step_name,
        )
        self._generating[item.id] = item
        self._notify_status()
        return item.id
    
    def update_progress(self, generating_id: str, progress: float):
        """Update generation progress."""
        if generating_id in self._generating:
            self._generating[generating_id].progress = progress
            item = self._generating[generating_id]
            
            if self._on_progress:
                self._on_progress(item.asset_id, item.step_id, progress)
    
    def finish_generating(self, generating_id: str):
        """Mark generation as complete."""
        if generating_id in self._generating:
            del self._generating[generating_id]
            self._notify_status()
    
    def start(self):
        """Start the background worker."""
        self._running = True
        self._paused = False
        self._notify_status()
    
    def pause(self):
        """Pause generation (but don't stop current tasks)."""
        self._paused = True
        self._notify_status()
    
    def resume(self):
        """Resume generation."""
        self._paused = False
        self._notify_status()
    
    def stop(self):
        """Stop generation."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
        self._notify_status()
    
    def _notify_status(self):
        """Notify listeners of status change."""
        if self._on_status_update:
            self._on_status_update(self.get_status())
    
    def clear(self):
        """Clear all queue state."""
        self._approval_queue.clear()
        self._generating.clear()
        self._completed.clear()
        self._assets.clear()
        self._pending_asset_ids.clear()
        self._running = False
        self._paused = False


# Global queue manager instance
_queue_manager: Optional[QueueManager] = None


def get_queue_manager() -> QueueManager:
    """Get or create the global queue manager."""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = QueueManager()
    return _queue_manager
