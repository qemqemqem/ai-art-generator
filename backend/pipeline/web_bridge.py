"""
Web Approval Bridge.

Provides async communication between the pipeline executor and a web browser
for human-in-the-loop interactions. Replaces CLI prompts when running in
web mode.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


class ApprovalType(str, Enum):
    """Type of approval needed."""
    SELECT_ONE = "select_one"  # Choose from variations
    APPROVE = "approve"  # Accept/reject single item


class PipelinePhase(str, Enum):
    """Current phase of pipeline execution."""
    LOADING = "loading"
    VALIDATING = "validating"
    RUNNING = "running"
    WAITING = "waiting"  # Waiting for user input
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ApprovalRequest:
    """A request for user approval/selection."""
    id: str = field(default_factory=lambda: str(uuid4()))
    type: ApprovalType = ApprovalType.SELECT_ONE
    step_id: str = ""
    step_type: str = ""  # e.g., "generate_image", "generate_text"
    asset_id: str | None = None
    asset_name: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    prompt: str = ""  # What user sees as instruction
    generation_prompt: str = ""  # The actual prompt sent to AI
    step_description: str = ""  # Description of what this step does
    metadata: dict[str, Any] = field(default_factory=dict)  # Additional context
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "step_id": self.step_id,
            "step_type": self.step_type,
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "options": self.options,
            "prompt": self.prompt,
            "generation_prompt": self.generation_prompt,
            "step_description": self.step_description,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ApprovalResponse:
    """Response from user approval."""
    request_id: str
    approved: bool = True
    selected_index: int | None = None
    regenerate: bool = False


@dataclass
class StepInfo:
    """Information about a pipeline step for display."""
    id: str
    type: str
    description: str = ""
    for_each: str | None = None  # "asset" or None (global)
    status: str = "pending"  # "pending", "running", "complete", "skipped"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "for_each": self.for_each,
            "status": self.status,
        }


@dataclass
class PipelineProgress:
    """Current pipeline progress state."""
    phase: PipelinePhase = PipelinePhase.LOADING
    pipeline_name: str = ""
    pipeline_description: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    current_step: str = ""
    current_step_type: str = ""
    current_step_description: str = ""
    current_step_prompt: str = ""  # The generation prompt being used
    total_assets: int = 0
    completed_assets: int = 0
    current_asset: str = ""
    current_asset_data: dict[str, Any] = field(default_factory=dict)  # Full asset info
    context_data: dict[str, Any] = field(default_factory=dict)  # Full context info
    message: str = ""
    errors: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    pipeline_steps: list[StepInfo] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "pipeline_name": self.pipeline_name,
            "pipeline_description": self.pipeline_description,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "current_step": self.current_step,
            "current_step_type": self.current_step_type,
            "current_step_description": self.current_step_description,
            "current_step_prompt": self.current_step_prompt,
            "total_assets": self.total_assets,
            "completed_assets": self.completed_assets,
            "current_asset": self.current_asset,
            "current_asset_data": self.current_asset_data,
            "context_data": self.context_data,
            "message": self.message,
            "errors": self.errors,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "percent": self._calc_percent(),
            "pipeline_steps": [s.to_dict() for s in self.pipeline_steps],
        }
    
    def _calc_percent(self) -> int:
        """Calculate overall completion percentage."""
        if self.phase == PipelinePhase.COMPLETE:
            return 100
        if self.phase == PipelinePhase.FAILED:
            return 0
        if self.total_steps == 0:
            return 0
        
        # Weight steps and assets
        step_weight = self.completed_steps / self.total_steps
        if self.total_assets > 0 and self.completed_assets > 0:
            asset_weight = self.completed_assets / self.total_assets
            return int((step_weight * 0.7 + asset_weight * 0.3) * 100)
        return int(step_weight * 100)


class WebApprovalBridge:
    """
    Bridge between pipeline executor and web browser for approvals.
    
    Usage:
        bridge = WebApprovalBridge()
        
        # In executor, instead of CLI prompts:
        selected = await bridge.request_selection(
            step_id="generate_art",
            asset_name="Fire Dragon",
            options=[{"path": "img1.png"}, {"path": "img2.png"}]
        )
        
        # In web server:
        bridge.submit_response(ApprovalResponse(request_id="...", selected_index=1))
    """
    
    def __init__(self):
        self._pending_requests: dict[str, ApprovalRequest] = {}
        self._response_events: dict[str, asyncio.Event] = {}
        self._response_loops: dict[str, asyncio.AbstractEventLoop] = {}  # Track which loop owns each event
        self._responses: dict[str, ApprovalResponse] = {}
        self._progress = PipelineProgress()
        self._broadcast_callback: Callable[[dict], None] | None = None
        self._shutdown_requested = False
        self._shutdown_event: asyncio.Event | None = None
        self._shutdown_loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()
    
    def set_broadcast_callback(self, callback: Callable[[dict], None]) -> None:
        """Set callback for broadcasting updates to WebSocket clients."""
        self._broadcast_callback = callback
    
    def _broadcast(self, message_type: str, data: dict[str, Any]) -> None:
        """Broadcast a message to connected clients."""
        if self._broadcast_callback:
            try:
                self._broadcast_callback({
                    "type": message_type,
                    "data": data,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass  # Don't let broadcast errors affect pipeline
    
    # --- Progress Updates ---
    
    def update_progress(self, **kwargs) -> None:
        """Update pipeline progress and broadcast."""
        for key, value in kwargs.items():
            if hasattr(self._progress, key):
                setattr(self._progress, key, value)
        self._broadcast("progress", self._progress.to_dict())
    
    def get_progress(self) -> PipelineProgress:
        """Get current progress state."""
        return self._progress
    
    def set_phase(self, phase: PipelinePhase, message: str = "") -> None:
        """Set the pipeline phase with optional message."""
        self._progress.phase = phase
        if message:
            self._progress.message = message
        self._broadcast("progress", self._progress.to_dict())
    
    # --- Approval Requests ---
    
    async def request_selection(
        self,
        step_id: str,
        asset_name: str,
        options: list[dict[str, Any]],
        asset_id: str | None = None,
        prompt: str = "",
        step_type: str = "",
        generation_prompt: str = "",
        step_description: str = "",
        metadata: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bool]:
        """
        Request user to select from options.
        
        Returns:
            Tuple of (selected_index, regenerate_requested)
        """
        request = ApprovalRequest(
            type=ApprovalType.SELECT_ONE,
            step_id=step_id,
            step_type=step_type,
            asset_id=asset_id,
            asset_name=asset_name,
            options=options,
            prompt=prompt or f"Select best option for {asset_name}",
            generation_prompt=generation_prompt,
            step_description=step_description,
            metadata=metadata or {},
        )
        
        return await self._wait_for_response(request, timeout)
    
    async def request_approval(
        self,
        step_id: str,
        asset_name: str,
        result: dict[str, Any],
        asset_id: str | None = None,
        prompt: str = "",
        step_type: str = "",
        generation_prompt: str = "",
        step_description: str = "",
        metadata: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[bool, bool]:
        """
        Request user approval for a single result.
        
        Returns:
            Tuple of (approved, regenerate_requested)
        """
        request = ApprovalRequest(
            type=ApprovalType.APPROVE,
            step_id=step_id,
            step_type=step_type,
            asset_id=asset_id,
            asset_name=asset_name,
            options=[result],
            prompt=prompt or f"Approve result for {asset_name}?",
            generation_prompt=generation_prompt,
            step_description=step_description,
            metadata=metadata or {},
        )
        
        index, regenerate = await self._wait_for_response(request, timeout)
        return (index == 0 and not regenerate), regenerate
    
    async def _wait_for_response(
        self,
        request: ApprovalRequest,
        timeout: float | None = None,
    ) -> tuple[int, bool]:
        """Wait for a response to an approval request."""
        # Get the current event loop (the one running the pipeline)
        loop = asyncio.get_running_loop()
        logger.debug(f"_wait_for_response: request_id={request.id}")
        logger.debug(f"  current loop={loop}, running={loop.is_running()}")
        
        async with self._lock:
            event = asyncio.Event()
            self._pending_requests[request.id] = request
            self._response_events[request.id] = event
            self._response_loops[request.id] = loop  # Track which loop owns this event
        
        logger.debug(f"  Event created and registered, waiting...")
        
        # Update progress to waiting
        self._progress.phase = PipelinePhase.WAITING
        self._progress.current_asset = request.asset_name
        
        # Broadcast the approval request
        self._broadcast("approval_request", request.to_dict())
        
        try:
            if timeout:
                await asyncio.wait_for(event.wait(), timeout)
            else:
                logger.debug(f"  Awaiting event.wait()...")
                await event.wait()
                logger.debug(f"  Event received!")
            
            response = self._responses.get(request.id)
            logger.debug(f"  Response: {response}")
            if response:
                return (response.selected_index or 0), response.regenerate
            return 0, False
            
        except asyncio.TimeoutError:
            logger.debug(f"  Timeout - auto-approving")
            # Auto-approve on timeout
            return 0, False
        finally:
            # Cleanup
            async with self._lock:
                self._pending_requests.pop(request.id, None)
                self._response_events.pop(request.id, None)
                self._response_loops.pop(request.id, None)
                self._responses.pop(request.id, None)
            
            logger.debug(f"  Resuming running phase")
            # Resume running phase and broadcast the change
            self._progress.phase = PipelinePhase.RUNNING
            self._broadcast("progress", self._progress.to_dict())
    
    def submit_response(self, response: ApprovalResponse) -> bool:
        """
        Submit a response to an approval request.
        
        This is called from the web server thread, so we need to use
        call_soon_threadsafe to set the event in the pipeline's event loop.
        
        Returns True if the request was found and responded to.
        """
        logger.debug(f"submit_response called for request_id={response.request_id}")
        logger.debug(f"  pending requests: {list(self._response_events.keys())}")
        
        if response.request_id not in self._response_events:
            logger.warning(f"Request {response.request_id} not found in pending events")
            return False
        
        self._responses[response.request_id] = response
        
        # Get the event and its owning loop
        event = self._response_events[response.request_id]
        loop = self._response_loops.get(response.request_id)
        
        logger.debug(f"  event={event}, event.is_set={event.is_set()}")
        logger.debug(f"  loop={loop}, loop.is_running={loop.is_running() if loop else 'N/A'}")
        
        if loop is not None:
            # Set the event from the correct loop (thread-safe)
            logger.debug(f"  Using call_soon_threadsafe to set event")
            try:
                loop.call_soon_threadsafe(event.set)
                logger.debug(f"  Event set successfully via call_soon_threadsafe")
            except Exception as e:
                logger.error(f"  Error setting event: {e}")
                # Try direct set as fallback
                event.set()
        else:
            # Fallback: direct set (may not work cross-thread)
            logger.warning(f"  No loop found, using direct event.set()")
            event.set()
        
        return True
    
    def get_pending_requests(self) -> list[ApprovalRequest]:
        """Get all pending approval requests."""
        return list(self._pending_requests.values())
    
    # --- Shutdown ---
    
    def request_shutdown(self) -> None:
        """Request server shutdown (called when user closes browser)."""
        self._shutdown_requested = True
        if self._shutdown_event and self._shutdown_loop:
            # Thread-safe event set
            self._shutdown_loop.call_soon_threadsafe(self._shutdown_event.set)
        elif self._shutdown_event:
            self._shutdown_event.set()
    
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested
    
    async def wait_for_shutdown(self) -> None:
        """Wait until shutdown is requested."""
        # Create the event in the current loop
        self._shutdown_loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()
        await self._shutdown_event.wait()


# Global instance for the current pipeline run
_bridge: WebApprovalBridge | None = None


def get_bridge() -> WebApprovalBridge:
    """Get or create the global bridge instance."""
    global _bridge
    if _bridge is None:
        _bridge = WebApprovalBridge()
    return _bridge


def reset_bridge() -> WebApprovalBridge:
    """Reset and return a new bridge instance."""
    global _bridge
    _bridge = WebApprovalBridge()
    return _bridge
