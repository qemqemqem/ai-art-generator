"""WebSocket handler for real-time updates.

Provides live updates to connected clients about:
- Queue status changes
- New items awaiting approval
- Generation progress
- Errors
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    """Manages WebSocket connections."""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
    
    async def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket."""
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict[str, Any]):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return
        
        text = json.dumps(message, default=str)
        
        async with self._lock:
            disconnected = []
            for connection in self.active_connections:
                try:
                    await connection.send_text(text)
                except Exception:
                    disconnected.append(connection)
            
            # Clean up disconnected
            for conn in disconnected:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)
    
    async def send_to(self, websocket: WebSocket, message: dict[str, Any]):
        """Send a message to a specific client."""
        text = json.dumps(message, default=str)
        await websocket.send_text(text)


# Global connection manager
manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager."""
    return manager


# Message types for WebSocket communication

async def broadcast_queue_update(status: dict[str, Any]):
    """Broadcast queue status update."""
    await manager.broadcast({
        "type": "queue_update",
        "timestamp": datetime.utcnow().isoformat(),
        "status": status,
    })


async def broadcast_new_approval(item: dict[str, Any]):
    """Broadcast new approval item."""
    await manager.broadcast({
        "type": "new_approval",
        "timestamp": datetime.utcnow().isoformat(),
        "item": item,
    })


async def broadcast_progress(asset_id: str, step_id: str, progress: float):
    """Broadcast generation progress."""
    await manager.broadcast({
        "type": "generation_progress",
        "timestamp": datetime.utcnow().isoformat(),
        "asset_id": asset_id,
        "step_id": step_id,
        "progress": progress,
    })


async def broadcast_complete(asset_id: str, step_id: str):
    """Broadcast generation complete."""
    await manager.broadcast({
        "type": "generation_complete",
        "timestamp": datetime.utcnow().isoformat(),
        "asset_id": asset_id,
        "step_id": step_id,
    })


async def broadcast_error(asset_id: str, step_id: str, error: str):
    """Broadcast generation error."""
    await manager.broadcast({
        "type": "generation_error",
        "timestamp": datetime.utcnow().isoformat(),
        "asset_id": asset_id,
        "step_id": step_id,
        "error": error,
    })


def setup_queue_callbacks():
    """Set up callbacks from QueueManager to WebSocket broadcasts."""
    from app.queue_manager import get_queue_manager
    
    queue_manager = get_queue_manager()
    
    def on_status_update(status):
        asyncio.create_task(broadcast_queue_update(status.model_dump()))
    
    def on_new_approval(item):
        asyncio.create_task(broadcast_new_approval(item.model_dump()))
    
    def on_progress(asset_id: str, step_id: str, progress: float):
        asyncio.create_task(broadcast_progress(asset_id, step_id, progress))
    
    queue_manager.set_callbacks(
        on_status_update=on_status_update,
        on_new_approval=on_new_approval,
        on_progress=on_progress,
    )
