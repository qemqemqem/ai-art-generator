"""
Web Server for CLI Pipeline Mode.

A minimal FastAPI server that runs alongside CLI pipeline execution,
providing a web interface for human-in-the-loop interactions.
"""

import asyncio
import json
import os
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .web_bridge import (
    ApprovalResponse,
    PipelinePhase,
    get_bridge,
    reset_bridge,
)


# --- WebSocket Manager ---

class ConnectionManager:
    """Manages WebSocket connections."""
    
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
    
    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        async with self._lock:
            dead = []
            for ws in self._connections:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.remove(ws)
    
    def broadcast_sync(self, message: dict):
        """Sync wrapper for broadcast (for use from non-async context)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.broadcast(message))
            else:
                loop.run_until_complete(self.broadcast(message))
        except RuntimeError:
            # No event loop - we're likely shutting down
            pass
    
    @property
    def connection_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


# --- FastAPI App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - setup and teardown."""
    # Setup: connect bridge to websocket broadcast
    bridge = get_bridge()
    bridge.set_broadcast_callback(manager.broadcast_sync)
    yield
    # Teardown: nothing needed


app = FastAPI(
    title="ArtGen Pipeline",
    description="Web interface for pipeline execution",
    lifespan=lifespan,
)

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API Routes ---

@app.get("/")
async def root():
    """Serve the main HTML page."""
    return HTMLResponse(content=get_html_page(), status_code=200)


@app.get("/api/status")
async def get_status():
    """Get current pipeline status."""
    bridge = get_bridge()
    return {
        "progress": bridge.get_progress().to_dict(),
        "pending": [r.to_dict() for r in bridge.get_pending_requests()],
        "connections": manager.connection_count,
    }


@app.get("/api/pending")
async def get_pending():
    """Get pending approval requests."""
    bridge = get_bridge()
    return {
        "requests": [r.to_dict() for r in bridge.get_pending_requests()]
    }


class SubmitApprovalRequest(BaseModel):
    """Request to submit an approval decision."""
    request_id: str
    approved: bool = True
    selected_index: int | None = None
    regenerate: bool = False


@app.post("/api/approve")
async def submit_approval(request: SubmitApprovalRequest):
    """Submit an approval decision."""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"Received approval: request_id={request.request_id}, approved={request.approved}, selected_index={request.selected_index}")
    
    bridge = get_bridge()
    
    response = ApprovalResponse(
        request_id=request.request_id,
        approved=request.approved,
        selected_index=request.selected_index,
        regenerate=request.regenerate,
    )
    
    result = bridge.submit_response(response)
    logger.info(f"submit_response returned: {result}")
    
    if result:
        return {"status": "ok", "message": "Decision submitted"}
    else:
        raise HTTPException(404, "Request not found or already handled")


@app.post("/api/shutdown")
async def shutdown():
    """Request server shutdown."""
    bridge = get_bridge()
    bridge.request_shutdown()
    return {"status": "ok", "message": "Shutdown requested"}


@app.get("/api/step/{step_id}/asset-status")
async def get_step_asset_status(step_id: str):
    """Get which assets have completed a specific step."""
    if _base_path is None:
        raise HTTPException(500, "Server not configured")
    
    state_dir = _base_path / ".artgen"
    step_dir = state_dir / step_id
    
    # Check which assets have outputs for this step
    completed_assets = []
    
    if step_dir.exists():
        # Check for per-asset outputs
        for asset_dir in step_dir.iterdir():
            if asset_dir.is_dir():
                output_file = asset_dir / "output.json"
                if output_file.exists():
                    completed_assets.append(asset_dir.name)
    
    return {
        "step_id": step_id,
        "completed_assets": completed_assets,
    }


@app.get("/api/history/{step_id}")
async def get_step_history(step_id: str, asset_id: str = None):
    """Get history data for a completed step, optionally filtered by asset."""
    if _base_path is None:
        raise HTTPException(500, "Server not configured")
    
    state_dir = _base_path / ".artgen"
    step_dir = state_dir / step_id
    
    if not step_dir.exists():
        raise HTTPException(404, f"No history for step: {step_id}")
    
    import json
    
    # Gather all outputs for this step
    outputs = []
    files = set()  # Use set to avoid duplicates
    saved_paths = []  # Track where files were saved
    
    def extract_files_from_output(output_data: dict, for_asset_id: str = None, source_path: Path = None) -> None:
        """Extract file paths from output data."""
        if not isinstance(output_data, dict):
            return
        for key in ["paths", "path", "selected_path", "output_path", "image_path"]:
            val = output_data.get(key)
            if isinstance(val, list):
                # Filter paths by asset_id if provided
                for path_str in val:
                    if not asset_id or (for_asset_id and for_asset_id == asset_id) or asset_id in path_str:
                        files.add(path_str)
            elif isinstance(val, str) and val:
                if not asset_id or (for_asset_id and for_asset_id == asset_id) or asset_id in val:
                    files.add(val)
    
    # Check for global step output (only if not filtering by asset)
    if not asset_id:
        global_output = state_dir / step_id / "output.json"
        if global_output.exists():
            try:
                with open(global_output) as f:
                    data = json.load(f)
                    output_data = data.get("data", {})
                    
                    # Calculate relative path for display
                    rel_cache_path = str(global_output.relative_to(_base_path))
                    saved_paths.append(rel_cache_path)
                    
                    outputs.append({
                        "type": "global",
                        "data": output_data,
                        "timestamp": data.get("timestamp"),
                        "selected_index": output_data.get("selected_index") if isinstance(output_data, dict) else None,
                        "cache_path": rel_cache_path,
                    })
                    extract_files_from_output(output_data, source_path=global_output)
            except (json.JSONDecodeError, IOError):
                pass
    
    # Check for per-asset outputs
    for asset_dir in step_dir.iterdir():
        if asset_dir.is_dir():
            # Skip if filtering by asset and this isn't the one
            if asset_id and asset_dir.name != asset_id:
                continue
                
            output_file = asset_dir / "output.json"
            if output_file.exists():
                try:
                    with open(output_file) as f:
                        data = json.load(f)
                        output_data = data.get("data", {})
                        
                        # Calculate relative path for display
                        rel_cache_path = str(output_file.relative_to(_base_path))
                        saved_paths.append(rel_cache_path)
                        
                        # Build comprehensive output entry
                        entry = {
                            "type": "per_asset",
                            "asset_id": asset_dir.name,
                            "data": output_data,
                            "timestamp": data.get("timestamp"),
                            "selected_index": None,
                            "cache_path": rel_cache_path,
                        }
                        
                        # Extract selection info
                        if isinstance(output_data, dict):
                            entry["selected_index"] = output_data.get("selected_index")
                            # Check for assessment-specific fields
                            if "assessment" in output_data:
                                entry["assessment"] = output_data["assessment"]
                            if "approved" in output_data:
                                entry["approved"] = output_data["approved"]
                            if "verdict" in output_data:
                                entry["verdict"] = output_data["verdict"]
                        
                        outputs.append(entry)
                        extract_files_from_output(output_data, asset_dir.name, source_path=output_file)
                except (json.JSONDecodeError, IOError):
                    pass
    
    # Convert to relative paths and filter to only image files
    relative_files = []
    for f in files:
        path = Path(f)
        if path.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
            # Convert to relative path from base_path if it's absolute
            try:
                if path.is_absolute():
                    path = path.relative_to(_base_path)
                relative_files.append(str(path))
            except ValueError:
                relative_files.append(str(path))
    
    # Determine the main cache directory for this step
    cache_dir = str(step_dir.relative_to(_base_path)) if step_dir.exists() else None
    
    return {
        "step_id": step_id,
        "asset_id": asset_id,
        "outputs": outputs,
        "files": sorted(relative_files),
        "cache_dir": cache_dir,
        "saved_paths": saved_paths,
    }


@app.get("/api/assets")
async def get_assets():
    """Get current list of assets with their status per step."""
    bridge = get_bridge()
    progress = bridge.get_progress()
    
    # This returns basic asset info - full implementation would track per-asset status
    return {
        "total": progress.total_assets,
        "completed": progress.completed_assets,
        "current": progress.current_asset,
    }


@app.get("/api/saved-files")
async def get_saved_files():
    """Get summary of all saved files across the pipeline."""
    if _base_path is None:
        raise HTTPException(500, "Server not configured")
    
    state_dir = _base_path / ".artgen"
    if not state_dir.exists():
        return {"cache_dir": None, "steps": [], "total_files": 0, "total_size_bytes": 0}
    
    import json
    
    steps = []
    total_files = 0
    total_size = 0
    
    # Scan all step directories
    for step_dir in sorted(state_dir.iterdir()):
        if not step_dir.is_dir():
            continue
        
        step_info = {
            "step_id": step_dir.name,
            "path": str(step_dir.relative_to(_base_path)),
            "files": [],
            "file_count": 0,
            "size_bytes": 0,
        }
        
        # Collect all files in this step
        for file_path in step_dir.rglob("*"):
            if file_path.is_file():
                try:
                    size = file_path.stat().st_size
                    step_info["files"].append({
                        "path": str(file_path.relative_to(_base_path)),
                        "name": file_path.name,
                        "size_bytes": size,
                        "type": file_path.suffix.lower().lstrip("."),
                    })
                    step_info["file_count"] += 1
                    step_info["size_bytes"] += size
                    total_files += 1
                    total_size += size
                except OSError:
                    pass
        
        if step_info["file_count"] > 0:
            steps.append(step_info)
    
    # Format total size for display
    def format_size(size_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
    
    return {
        "cache_dir": str(state_dir.relative_to(_base_path)),
        "steps": steps,
        "total_files": total_files,
        "total_size_bytes": total_size,
        "total_size_formatted": format_size(total_size),
    }


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    bridge = get_bridge()
    
    try:
        # Send initial state
        await websocket.send_json({
            "type": "connected",
            "data": {
                "progress": bridge.get_progress().to_dict(),
                "pending": [r.to_dict() for r in bridge.get_pending_requests()],
            },
        })
        
        # Keep connection alive
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    # Send JSON response so client can parse it
                    await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                break
    finally:
        await manager.disconnect(websocket)
        
        # If this was the last connection, request shutdown
        if manager.connection_count == 0:
            # Give a small delay for reconnection attempts
            await asyncio.sleep(2)
            if manager.connection_count == 0:
                bridge.request_shutdown()


# --- Static Files (images) ---

# This will be set when the server starts
_base_path: Path | None = None


def set_base_path(path: Path):
    """Set the base path for serving files."""
    global _base_path
    _base_path = path


@app.get("/files/{file_path:path}")
async def serve_file(file_path: str):
    """Serve files from the pipeline directory."""
    if _base_path is None:
        raise HTTPException(500, "Server not configured")
    
    full_path = _base_path / file_path
    if not full_path.exists():
        raise HTTPException(404, f"File not found: {file_path}")
    
    return FileResponse(full_path)


# --- HTML Page ---

def get_html_page() -> str:
    """Return the inline HTML/CSS/JS for the web interface."""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ArtGen Pipeline</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #ffffff;
            color: #1a1a1a;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        /* ===== TOP PIPELINE BAR ===== */
        .pipeline-bar {
            background: #f8fafc;
            border-bottom: 1px solid #e2e8f0;
            padding: 16px 24px;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .pipeline-bar-inner {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .pipeline-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        
        .pipeline-title {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .pipeline-title h1 {
            font-size: 16px;
            font-weight: 600;
        }
        
        .pipeline-title .percent {
            font-size: 14px;
            font-weight: 600;
            color: #3b82f6;
        }
        
        .status-badge {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: #64748b;
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #22c55e;
        }
        
        .status-dot.waiting { background: #f59e0b; animation: pulse 2s infinite; }
        .status-dot.error { background: #ef4444; }
        
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        
        /* Queue Button */
        .queue-btn {
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 42px;
            height: 42px;
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.15s;
        }
        .queue-btn:hover { background: #e2e8f0; border-color: #cbd5e1; }
        .queue-btn.has-items { background: #fef3c7; border-color: #fcd34d; animation: queuePulse 2s ease-in-out infinite; }
        .queue-btn.has-items:hover { background: #fde68a; animation: none; }
        
        @keyframes queuePulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(251, 191, 36, 0); }
            50% { box-shadow: 0 0 0 8px rgba(251, 191, 36, 0.3); }
        }
        
        .queue-icon { font-size: 20px; }
        
        .queue-badge {
            position: absolute;
            top: -6px;
            right: -6px;
            min-width: 20px;
            height: 20px;
            padding: 0 6px;
            background: #ef4444;
            color: white;
            font-size: 11px;
            font-weight: 600;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .queue-badge.empty { display: none; }
        
        /* Queue Mode Overlay */
        .queue-mode {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: #f8fafc;
            z-index: 500;
            flex-direction: column;
        }
        .queue-mode.visible { display: flex; }
        
        .queue-mode-header {
            background: white;
            border-bottom: 1px solid #e2e8f0;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .queue-mode-title {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .queue-mode-title h2 {
            font-size: 18px;
            font-weight: 600;
            margin: 0;
        }
        
        .queue-progress {
            font-size: 14px;
            color: #64748b;
            background: #f1f5f9;
            padding: 6px 14px;
            border-radius: 16px;
        }
        
        .queue-mode-close {
            padding: 8px 16px;
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            font-size: 14px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .queue-mode-close:hover { background: #e2e8f0; }
        
        .queue-mode-content {
            flex: 1;
            overflow-y: auto;
            padding: 32px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        
        .queue-item-container {
            width: 100%;
            max-width: 800px;
        }
        
        .queue-item-header {
            margin-bottom: 24px;
            text-align: center;
        }
        
        .queue-item-asset {
            font-size: 12px;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }
        
        .queue-item-title {
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        
        .queue-item-subtitle {
            font-size: 15px;
            color: #64748b;
        }
        
        .queue-options-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        
        .queue-option-card {
            background: white;
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            overflow: hidden;
            cursor: pointer;
            transition: all 0.15s;
        }
        .queue-option-card:hover { 
            border-color: #3b82f6;
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(59, 130, 246, 0.15);
        }
        .queue-option-card.selected { border-color: #22c55e; background: #f0fdf4; }
        
        .queue-option-image {
            width: 100%;
            aspect-ratio: 1;
            object-fit: cover;
            background: #f1f5f9;
        }
        
        .queue-option-text {
            padding: 16px;
            font-size: 14px;
            line-height: 1.6;
            max-height: 200px;
            overflow-y: auto;
            white-space: pre-wrap;
        }
        
        .queue-option-footer {
            padding: 12px 16px;
            border-top: 1px solid #e2e8f0;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        
        .queue-option-number {
            width: 28px;
            height: 28px;
            background: #e2e8f0;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: 600;
        }
        .queue-option-card:hover .queue-option-number { background: #3b82f6; color: white; }
        .queue-option-card.selected .queue-option-number { background: #22c55e; color: white; }
        
        .queue-option-label { font-size: 14px; font-weight: 500; }
        
        .queue-actions {
            display: flex;
            justify-content: center;
            gap: 12px;
            padding-top: 24px;
            border-top: 1px solid #e2e8f0;
        }
        
        .queue-btn-primary {
            padding: 12px 28px;
            background: #3b82f6;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s;
        }
        .queue-btn-primary:hover { background: #2563eb; }
        .queue-btn-primary:disabled { background: #94a3b8; cursor: not-allowed; }
        
        .queue-btn-secondary {
            padding: 12px 24px;
            background: white;
            color: #475569;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            font-size: 15px;
            cursor: pointer;
            transition: all 0.15s;
        }
        .queue-btn-secondary:hover { background: #f8fafc; border-color: #cbd5e1; }
        
        .queue-btn-skip {
            padding: 12px 24px;
            background: transparent;
            color: #94a3b8;
            border: 1px dashed #e2e8f0;
            border-radius: 8px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.15s;
        }
        .queue-btn-skip:hover { color: #64748b; border-color: #cbd5e1; }
        
        .queue-shortcuts {
            margin-top: 24px;
            text-align: center;
            font-size: 13px;
            color: #94a3b8;
        }
        
        .queue-shortcuts kbd {
            display: inline-block;
            padding: 3px 8px;
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 4px;
            font-family: monospace;
            font-size: 12px;
            margin: 0 2px;
        }
        
        .queue-empty {
            text-align: center;
            padding: 80px 20px;
        }
        
        .queue-empty-icon {
            font-size: 64px;
            margin-bottom: 20px;
            opacity: 0.5;
        }
        
        .queue-empty-title {
            font-size: 20px;
            font-weight: 600;
            color: #64748b;
            margin-bottom: 8px;
        }
        
        .queue-empty-text {
            font-size: 15px;
            color: #94a3b8;
        }
        
        /* Queue Approval Layout (single item) */
        .queue-approval-layout {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 32px;
            padding: 20px 0;
        }
        
        .queue-approval-preview {
            max-width: 400px;
            width: 100%;
        }
        
        .queue-approval-image {
            width: 100%;
            max-height: 400px;
            object-fit: contain;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
            cursor: zoom-in;
        }
        
        .queue-approval-text {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 24px;
            font-size: 15px;
            line-height: 1.7;
            max-height: 300px;
            overflow-y: auto;
            white-space: pre-wrap;
        }
        
        .queue-approval-actions {
            display: flex;
            gap: 20px;
            justify-content: center;
        }
        
        .queue-approve-btn {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
            padding: 24px 48px;
            border: 2px solid #e2e8f0;
            border-radius: 16px;
            background: white;
            cursor: pointer;
            transition: all 0.15s;
            min-width: 160px;
        }
        
        .queue-approve-btn:hover { transform: translateY(-2px); }
        
        .queue-approve-btn.accept {
            border-color: #86efac;
            background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
        }
        .queue-approve-btn.accept:hover {
            border-color: #22c55e;
            box-shadow: 0 8px 24px rgba(34, 197, 94, 0.2);
        }
        
        .queue-approve-btn.reject {
            border-color: #fecaca;
            background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
        }
        .queue-approve-btn.reject:hover {
            border-color: #ef4444;
            box-shadow: 0 8px 24px rgba(239, 68, 68, 0.2);
        }
        
        .queue-approve-icon {
            font-size: 32px;
            line-height: 1;
        }
        .queue-approve-btn.accept .queue-approve-icon { color: #22c55e; }
        .queue-approve-btn.reject .queue-approve-icon { color: #ef4444; }
        
        .queue-approve-label {
            font-size: 18px;
            font-weight: 600;
        }
        .queue-approve-btn.accept .queue-approve-label { color: #166534; }
        .queue-approve-btn.reject .queue-approve-label { color: #991b1b; }
        
        .queue-approve-keys {
            font-size: 12px;
            color: #94a3b8;
        }
        .queue-approve-keys kbd {
            background: rgba(0,0,0,0.05);
            border: 1px solid rgba(0,0,0,0.1);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: monospace;
        }
        
        /* Pipeline Steps Row */
        .pipeline-steps-row {
            display: flex;
            align-items: center;
            gap: 4px;
            overflow-x: auto;
            padding-bottom: 4px;
        }
        
        .pipeline-step-chip {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 14px;
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 20px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.15s;
            white-space: nowrap;
            flex-shrink: 0;
        }
        
        .pipeline-step-chip:hover { border-color: #3b82f6; background: #f8fafc; }
        .pipeline-step-chip.active { border-color: #3b82f6; background: #eff6ff; }
        .pipeline-step-chip.complete { opacity: 0.7; }
        .pipeline-step-chip.complete:hover { opacity: 1; }
        .pipeline-step-chip.viewing { border-color: #8b5cf6; background: #f5f3ff; }
        .pipeline-step-chip.pending { opacity: 0.6; }
        .pipeline-step-chip.pending:hover { opacity: 0.8; }
        .pipeline-step-chip.fin-step { background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%); border-color: #16a34a; }
        .pipeline-step-chip.fin-step .step-chip-icon { background: white; color: #16a34a; }
        .pipeline-step-chip.fin-step span { color: white; }
        .pipeline-step-chip.fin-step:hover { background: linear-gradient(135deg, #16a34a 0%, #15803d 100%); }
        
        .step-chip-icon {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            flex-shrink: 0;
        }
        
        .step-chip-icon.pending { background: #e2e8f0; color: #94a3b8; }
        .step-chip-icon.running { background: #3b82f6; color: white; }
        .step-chip-icon.complete { background: #22c55e; color: white; }
        .step-chip-icon.failed { background: #ef4444; color: white; }
        .step-chip-icon.skipped { background: #94a3b8; color: white; }
        
        .step-connector {
            width: 20px;
            height: 2px;
            background: #e2e8f0;
            flex-shrink: 0;
        }
        
        .step-connector.complete { background: #22c55e; }
        
        /* ===== MAIN LAYOUT ===== */
        .main-container {
            flex: 1;
            display: flex;
            max-width: 1400px;
            margin: 0 auto;
            width: 100%;
        }
        
        /* Left Sidebar */
        .sidebar {
            width: 280px;
            border-right: 1px solid #e2e8f0;
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }
        
        .sidebar-section {
            padding: 20px;
            border-bottom: 1px solid #e2e8f0;
        }
        
        .sidebar-section:last-child { border-bottom: none; }
        
        .sidebar-title {
            font-size: 11px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 12px;
        }
        
        /* Stage Info */
        .stage-info {
            background: #f8fafc;
            border-radius: 8px;
            padding: 12px;
        }
        
        .stage-info.future-stage { background: #f1f5f9; border: 1px dashed #cbd5e1; }
        
        .stage-info-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 8px;
        }
        
        .stage-info-icon {
            font-size: 20px;
        }
        
        .stage-info-name {
            font-weight: 600;
            font-size: 14px;
        }
        
        .stage-info-type {
            font-size: 11px;
            color: #64748b;
            background: #e2e8f0;
            padding: 2px 8px;
            border-radius: 4px;
            margin-top: 2px;
            display: inline-block;
        }
        
        .stage-info-desc {
            font-size: 13px;
            color: #475569;
            margin-top: 8px;
            line-height: 1.5;
        }
        
        .stage-status-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 11px;
            font-weight: 500;
            padding: 4px 10px;
            border-radius: 12px;
            margin-top: 10px;
        }
        
        .stage-status-badge.pending { background: #f1f5f9; color: #64748b; }
        .stage-status-badge.running { background: #dbeafe; color: #1d4ed8; }
        .stage-status-badge.complete { background: #dcfce7; color: #166534; }
        .stage-status-badge.not-started { background: #fef3c7; color: #92400e; }
        
        /* Asset List */
        .asset-list {
            flex: 1;
            overflow-y: auto;
            padding: 0;
        }
        
        .asset-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 12px 20px;
            cursor: pointer;
            border-left: 3px solid transparent;
            transition: all 0.1s;
        }
        
        .asset-item:hover { background: #f8fafc; }
        .asset-item.selected { background: #eff6ff; border-left-color: #3b82f6; }
        .asset-item.processing { background: #fefce8; }
        .asset-item.needs-review { background: #fef3c7; border-left-color: #f59e0b; }
        
        .asset-status {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            flex-shrink: 0;
        }
        
        .asset-status.pending { background: #f1f5f9; color: #94a3b8; border: 1px solid #e2e8f0; }
        .asset-status.processing { background: #fef3c7; color: #d97706; }
        .asset-status.complete { background: #dcfce7; color: #16a34a; }
        .asset-status.failed { background: #fee2e2; color: #dc2626; }
        
        /* Spinner for processing */
        .asset-spinner {
            width: 16px;
            height: 16px;
            border: 2px solid #fef3c7;
            border-top: 2px solid #d97706;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        /* Warning icon for needs review */
        .asset-warning {
            width: 18px;
            height: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #fef3c7;
            color: #d97706;
            font-size: 12px;
            font-weight: bold;
            border-radius: 3px;
            position: relative;
        }
        
        .asset-warning::before {
            content: '';
            position: absolute;
            width: 0;
            height: 0;
            border-left: 9px solid transparent;
            border-right: 9px solid transparent;
            border-bottom: 16px solid #f59e0b;
            top: 1px;
        }
        
        .asset-warning::after {
            content: '!';
            position: relative;
            z-index: 1;
            color: white;
            font-size: 11px;
            font-weight: bold;
            top: 2px;
        }
        
        .asset-name {
            flex: 1;
            font-size: 13px;
            font-weight: 500;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        /* ===== MAIN CONTENT ===== */
        .content {
            flex: 1;
            padding: 24px 32px;
            overflow-y: auto;
        }
        
        /* History/Future Banner */
        .history-banner {
            display: none;
            background: #f5f3ff;
            border: 1px solid #c4b5fd;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 20px;
            align-items: center;
            gap: 12px;
        }
        
        .history-banner.visible { display: flex; }
        .history-banner.future { background: #fef3c7; border-color: #fcd34d; }
        .history-banner.future .history-banner-text { color: #92400e; }
        
        .history-banner-text {
            flex: 1;
            font-size: 13px;
            color: #6d28d9;
        }
        
        .history-banner-btn {
            padding: 6px 12px;
            background: #7c3aed;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
        }
        
        .history-banner-btn:hover { background: #6d28d9; }
        .history-banner.future .history-banner-btn { background: #d97706; }
        .history-banner.future .history-banner-btn:hover { background: #b45309; }
        
        /* Asset Details Card */
        .asset-details {
            background: #f8fafc;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }
        
        .asset-details.hidden { display: none; }
        
        .asset-details-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 16px;
        }
        
        .asset-details-title {
            font-size: 18px;
            font-weight: 600;
        }
        
        .asset-details-subtitle {
            font-size: 13px;
            color: #64748b;
            margin-top: 4px;
        }
        
        .asset-details-badge {
            font-size: 11px;
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: 500;
        }
        
        .asset-details-badge.pending { background: #f1f5f9; color: #64748b; }
        .asset-details-badge.processing { background: #fef3c7; color: #92400e; }
        .asset-details-badge.complete { background: #dcfce7; color: #166534; }
        
        /* Processing Info Box */
        .processing-info {
            background: linear-gradient(135deg, #fef3c7 0%, #fef9c3 100%);
            border: 1px solid #fcd34d;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
            display: none;
        }
        
        .processing-info.visible { display: flex; align-items: center; gap: 14px; }
        
        .processing-spinner {
            width: 28px;
            height: 28px;
            border: 3px solid #fef3c7;
            border-top: 3px solid #d97706;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            flex-shrink: 0;
        }
        
        .processing-text {
            flex: 1;
        }
        
        .processing-title {
            font-size: 14px;
            font-weight: 600;
            color: #92400e;
            margin-bottom: 2px;
        }
        
        .processing-detail {
            font-size: 12px;
            color: #b45309;
        }
        
        .asset-properties {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 12px;
        }
        
        .asset-prop {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px;
        }
        
        .asset-prop-label {
            font-size: 10px;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        
        .asset-prop-value {
            font-size: 13px;
            color: #1e293b;
            word-break: break-word;
        }
        
        /* Asset step output (shown during live view) */
        .asset-step-output {
            margin-top: 20px;
            padding-top: 16px;
            border-top: 1px solid #e2e8f0;
        }
        .asset-step-output .output-header {
            font-size: 12px;
            font-weight: 600;
            color: #16a34a;
            margin-bottom: 12px;
            text-transform: uppercase;
        }
        .asset-step-output .output-images {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
            gap: 8px;
            margin-bottom: 12px;
        }
        .asset-step-output .output-thumbnail {
            width: 100%;
            aspect-ratio: 1;
            object-fit: cover;
            border-radius: 6px;
            border: 1px solid #e2e8f0;
            cursor: zoom-in;
        }
        .asset-step-output .output-text {
            font-size: 13px;
            color: #374151;
            background: #f9fafb;
            padding: 10px;
            border-radius: 6px;
            margin-bottom: 8px;
            white-space: pre-wrap;
        }
        .asset-step-output .output-assessment {
            font-size: 12px;
            color: #6b7280;
            background: #f0fdf4;
            padding: 10px;
            border-radius: 6px;
            border-left: 3px solid #22c55e;
        }
        
        /* Prompt Box */
        .prompt-box {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
        }
        
        .prompt-box.hidden { display: none; }
        
        .prompt-box-label {
            font-size: 11px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        
        .prompt-box-text {
            font-size: 13px;
            color: #475569;
            line-height: 1.6;
            white-space: pre-wrap;
            max-height: 150px;
            overflow-y: auto;
        }
        
        /* Approval Section */
        .approval-section {
            display: none;
        }
        
        .approval-section.visible { display: block; }
        
        .approval-header {
            margin-bottom: 20px;
        }
        
        .approval-title {
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 6px;
        }
        
        .approval-subtitle {
            font-size: 14px;
            color: #64748b;
        }
        
        .options-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }
        
        .option-card {
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            overflow: hidden;
            cursor: pointer;
            transition: all 0.15s;
            position: relative;
            background: white;
        }
        
        .option-card:hover {
            border-color: #3b82f6;
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(59, 130, 246, 0.12);
        }
        
        .option-card.selected {
            border-color: #22c55e;
            background: #f0fdf4;
        }
        
        .option-card.history-selected {
            border-color: #8b5cf6;
            background: #faf5ff;
        }
        
        .option-image {
            width: 100%;
            aspect-ratio: 1;
            object-fit: cover;
            background: #f1f5f9;
        }
        
        .option-content {
            padding: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .option-number {
            width: 24px;
            height: 24px;
            background: #e2e8f0;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 600;
        }
        
        .option-card:hover .option-number { background: #3b82f6; color: white; }
        .option-card.selected .option-number { background: #22c55e; color: white; }
        
        .option-label {
            font-size: 13px;
            font-weight: 500;
        }
        
        .option-text {
            padding: 16px;
            font-size: 13px;
            line-height: 1.6;
            max-height: 200px;
            overflow-y: auto;
            white-space: pre-wrap;
        }
        
        .click-hint {
            position: absolute;
            top: 8px;
            right: 8px;
            background: rgba(0,0,0,0.7);
            color: white;
            font-size: 11px;
            padding: 4px 8px;
            border-radius: 4px;
            opacity: 0;
            transition: opacity 0.15s;
        }
        
        .option-card:hover .click-hint { opacity: 1; }
        
        /* Actions */
        .actions {
            display: flex;
            gap: 12px;
            padding-top: 16px;
            border-top: 1px solid #e2e8f0;
        }
        
        .btn {
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s;
            border: none;
        }
        
        .btn-secondary { background: #f1f5f9; color: #475569; }
        .btn-secondary:hover { background: #e2e8f0; }
        
        .keyboard-hints {
            margin-top: 16px;
            font-size: 12px;
            color: #94a3b8;
        }
        
        kbd {
            display: inline-block;
            padding: 2px 6px;
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            border-radius: 4px;
            font-family: monospace;
            font-size: 11px;
        }
        
        /* History View */
        .history-view {
            display: none;
        }
        
        .history-view.visible { display: block; }
        
        .history-asset-header {
            background: #f1f5f9;
            border-radius: 6px;
            padding: 10px 14px;
            margin-bottom: 16px;
            font-size: 13px;
            color: #475569;
        }
        .history-asset-header .history-asset-label {
            color: #64748b;
            margin-right: 6px;
        }
        .history-asset-header strong {
            color: #1e293b;
        }
        
        .history-output {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }
        
        .history-output.verdict {
            background: #f0fdf4;
            border-color: #86efac;
        }
        
        .history-output.verdict .history-output-label { color: #166534; }
        
        .history-output-label {
            font-size: 11px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            margin-bottom: 8px;
        }
        
        .history-output-content {
            font-size: 13px;
            color: #1e293b;
            white-space: pre-wrap;
            line-height: 1.6;
        }
        
        .history-images {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 12px;
        }
        
        .history-image-card {
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            overflow: hidden;
        }
        
        .history-image-card.was-selected {
            border-color: #8b5cf6;
        }
        
        .history-image-card img {
            width: 100%;
            aspect-ratio: 1;
            object-fit: cover;
        }
        
        .history-image-label {
            padding: 8px;
            font-size: 12px;
            color: #64748b;
            text-align: center;
            background: #f8fafc;
        }
        
        .history-image-card.was-selected .history-image-label {
            background: #f5f3ff;
            color: #7c3aed;
            font-weight: 500;
        }
        
        /* Future Step View */
        .future-step-view {
            display: none;
            text-align: center;
            padding: 40px 20px;
        }
        
        .future-step-view.visible { display: block; }
        
        .future-step-icon {
            width: 64px;
            height: 64px;
            background: #f1f5f9;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 16px;
            font-size: 28px;
            color: #94a3b8;
        }
        
        .future-step-title {
            font-size: 18px;
            font-weight: 600;
            color: #64748b;
            margin-bottom: 8px;
        }
        
        .future-step-desc {
            font-size: 14px;
            color: #94a3b8;
            max-width: 400px;
            margin: 0 auto 20px;
            line-height: 1.5;
        }
        
        .future-step-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            font-weight: 500;
            padding: 6px 14px;
            border-radius: 16px;
            background: #fef3c7;
            color: #92400e;
        }
        
        /* Complete Section (now shown when Fin step is clicked) */
        .complete-section {
            display: none;
            text-align: center;
            padding: 60px 20px;
        }
        
        .complete-section.visible { display: block; }
        
        .complete-icon {
            width: 64px;
            height: 64px;
            background: #22c55e;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 16px;
            color: white;
            font-size: 28px;
        }
        
        .complete-title {
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        
        .complete-subtitle {
            font-size: 14px;
            color: #64748b;
            margin-bottom: 24px;
        }
        
        .results-summary {
            display: inline-grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 32px;
            padding: 24px 40px;
            background: #f8fafc;
            border-radius: 12px;
            margin-bottom: 24px;
        }
        
        .result-value {
            font-size: 28px;
            font-weight: 600;
            color: #1e293b;
        }
        
        .result-label {
            font-size: 12px;
            color: #64748b;
        }
        
        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #94a3b8;
        }
        
        .empty-state-icon {
            font-size: 48px;
            margin-bottom: 16px;
        }
        
        .empty-state-text {
            font-size: 14px;
        }
        
        /* Responsive */
        @media (max-width: 900px) {
            .sidebar { width: 220px; }
        }
        
        @media (max-width: 700px) {
            .main-container { flex-direction: column; }
            .sidebar { width: 100%; border-right: none; border-bottom: 1px solid #e2e8f0; max-height: 300px; }
            .asset-list { max-height: 200px; }
        }
        
        /* Lightbox Modal */
        .lightbox {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.9);
            z-index: 10000;
            justify-content: center;
            align-items: center;
            flex-direction: column;
        }
        .lightbox.visible { display: flex; }
        
        .lightbox-content {
            position: relative;
            max-width: 90vw;
            max-height: 80vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        
        .lightbox-img {
            max-width: 100%;
            max-height: 80vh;
            object-fit: contain;
            transition: transform 0.2s ease;
            cursor: grab;
            border-radius: 4px;
            box-shadow: 0 10px 50px rgba(0, 0, 0, 0.5);
        }
        .lightbox-img.zoomed { cursor: move; }
        .lightbox-img.dragging { cursor: grabbing; }
        
        .lightbox-close {
            position: absolute;
            top: 20px;
            right: 20px;
            width: 44px;
            height: 44px;
            background: rgba(255, 255, 255, 0.1);
            border: none;
            border-radius: 50%;
            color: white;
            font-size: 24px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s;
            z-index: 10001;
        }
        .lightbox-close:hover { background: rgba(255, 255, 255, 0.2); }
        
        .lightbox-controls {
            display: flex;
            gap: 12px;
            margin-top: 20px;
        }
        
        .lightbox-btn {
            padding: 10px 20px;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 6px;
            color: white;
            font-size: 14px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: background 0.2s;
        }
        .lightbox-btn:hover { background: rgba(255, 255, 255, 0.2); }
        .lightbox-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .lightbox-zoom-level {
            color: rgba(255, 255, 255, 0.7);
            font-size: 13px;
            padding: 10px 16px;
            display: flex;
            align-items: center;
        }
        
        .lightbox-nav {
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            width: 50px;
            height: 50px;
            background: rgba(255, 255, 255, 0.1);
            border: none;
            border-radius: 50%;
            color: white;
            font-size: 24px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s;
        }
        .lightbox-nav:hover { background: rgba(255, 255, 255, 0.2); }
        .lightbox-nav.prev { left: 20px; }
        .lightbox-nav.next { right: 20px; }
        .lightbox-nav:disabled { opacity: 0.3; cursor: not-allowed; }
        
        .lightbox-caption {
            color: rgba(255, 255, 255, 0.8);
            font-size: 13px;
            margin-top: 12px;
            text-align: center;
        }
        
        /* Make images in history/approval/queue clickable */
        .history-image-card img,
        .option-preview img,
        .approval-images img,
        .queue-option-image {
            cursor: zoom-in;
        }
        
        /* Saved Files Indicators */
        .step-chip-save {
            font-size: 10px;
            margin-left: 4px;
            opacity: 0.6;
        }
        
        .saved-path-info {
            display: flex;
            align-items: center;
            gap: 8px;
            background: #f0fdf4;
            border: 1px solid #bbf7d0;
            border-radius: 6px;
            padding: 10px 14px;
            margin: 16px 0;
            font-size: 12px;
            color: #166534;
        }
        
        .saved-path-info.compact {
            padding: 6px 10px;
            margin: 8px 0;
            font-size: 11px;
        }
        
        .saved-path-icon {
            font-size: 14px;
            flex-shrink: 0;
        }
        
        .saved-path-text {
            flex: 1;
        }
        
        .saved-path-label {
            font-weight: 500;
            margin-bottom: 2px;
        }
        
        .saved-path-value {
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            color: #15803d;
            word-break: break-all;
        }
        
        .saved-path-copy {
            background: none;
            border: none;
            cursor: pointer;
            padding: 4px 8px;
            font-size: 11px;
            color: #22c55e;
            border-radius: 4px;
            transition: background 0.15s;
        }
        
        .saved-path-copy:hover {
            background: #dcfce7;
        }
        
        /* Saved Files Summary in Completion */
        .saved-files-summary {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 20px;
            margin-top: 24px;
            text-align: left;
            max-width: 500px;
            margin-left: auto;
            margin-right: auto;
        }
        
        .saved-files-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 16px;
            font-weight: 600;
            font-size: 14px;
            color: #1e293b;
        }
        
        .saved-files-header-icon {
            font-size: 18px;
        }
        
        .saved-files-stats {
            display: flex;
            gap: 20px;
            margin-bottom: 16px;
            padding-bottom: 16px;
            border-bottom: 1px solid #e2e8f0;
        }
        
        .saved-stat {
            text-align: center;
        }
        
        .saved-stat-value {
            font-size: 20px;
            font-weight: 600;
            color: #1e293b;
        }
        
        .saved-stat-label {
            font-size: 11px;
            color: #64748b;
            text-transform: uppercase;
        }
        
        .saved-files-path {
            background: #f1f5f9;
            border-radius: 6px;
            padding: 10px 12px;
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 12px;
            color: #475569;
            word-break: break-all;
        }
        
        .saved-files-path-label {
            font-size: 11px;
            color: #64748b;
            margin-bottom: 4px;
            font-family: inherit;
        }
        
        .saved-files-steps {
            margin-top: 12px;
        }
        
        .saved-step-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid #f1f5f9;
            font-size: 13px;
        }
        
        .saved-step-item:last-child {
            border-bottom: none;
        }
        
        .saved-step-name {
            color: #475569;
        }
        
        .saved-step-count {
            color: #94a3b8;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <!-- Top Pipeline Bar -->
    <div class="pipeline-bar">
        <div class="pipeline-bar-inner">
            <div class="pipeline-header">
                <div class="pipeline-title">
                    <h1 id="pipelineName">Loading pipeline...</h1>
                    <span class="percent" id="progressPercent">0%</span>
                </div>
                <div style="display: flex; align-items: center; gap: 16px;">
                    <button class="queue-btn" id="queueBtn" onclick="enterQueueMode()" title="Review Queue">
                        <span class="queue-icon">📋</span>
                        <span class="queue-badge" id="queueBadge">0</span>
                    </button>
                    <div class="status-badge">
                        <div class="status-dot" id="statusDot"></div>
                        <span id="statusText">Connecting...</span>
                    </div>
                </div>
            </div>
            <div class="pipeline-steps-row" id="pipelineStepsRow">
                <div style="color: #94a3b8; font-size: 13px;">Loading steps...</div>
            </div>
        </div>
    </div>
    
    <!-- Main Container -->
    <div class="main-container">
        <!-- Left Sidebar -->
        <aside class="sidebar">
            <div class="sidebar-section">
                <div class="sidebar-title" id="stageSectionTitle">Current Stage</div>
                <div class="stage-info" id="stageInfo">
                    <div class="stage-info-header">
                        <span class="stage-info-icon" id="stageIcon">▶</span>
                        <div>
                            <div class="stage-info-name" id="stageName">-</div>
                            <span class="stage-info-type" id="stageType">-</span>
                        </div>
                    </div>
                    <div class="stage-info-desc" id="stageDesc">Waiting to start...</div>
                    <div class="stage-status-badge pending" id="stageStatusBadge" style="display: none;">Not started yet</div>
                </div>
            </div>
            
            <div class="sidebar-section" style="flex: 1; display: flex; flex-direction: column; padding: 0;">
                <div class="sidebar-title" style="padding: 20px 20px 12px;">Assets <span id="assetCount">(0)</span></div>
                <div class="asset-list" id="assetList">
                    <div class="empty-state" style="padding: 20px;">
                        <div style="font-size: 13px;">No assets loaded</div>
                    </div>
                </div>
            </div>
        </aside>
        
        <!-- Main Content -->
        <main class="content">
            <!-- History Banner (shown when viewing past/future step) -->
            <div class="history-banner" id="historyBanner">
                <span class="history-banner-text" id="historyBannerText">Viewing history for step: <strong id="historyStepName">-</strong></span>
                <button class="history-banner-btn" id="backToCurrentBtn">Back to Current</button>
            </div>
            
            <!-- Approval Section (at top for visibility) -->
            <section class="approval-section" id="approvalSection">
                <div class="approval-header">
                    <h2 class="approval-title" id="approvalTitle">Select Best Option</h2>
                    <p class="approval-subtitle" id="approvalSubtitle">Click on an option to select it</p>
                </div>
                <div class="options-grid" id="optionsGrid"></div>
                <div class="actions">
                    <button class="btn btn-secondary" id="regenerateBtn">Regenerate All</button>
                </div>
                <div class="keyboard-hints">
                    <kbd>1</kbd>-<kbd>9</kbd> select &bull; <kbd>Y</kbd> approve &bull; <kbd>N</kbd>/<kbd>R</kbd> regenerate
                </div>
            </section>
            
            <!-- Asset Details -->
            <div class="asset-details hidden" id="assetDetails">
                <div class="asset-details-header">
                    <div>
                        <div class="asset-details-title" id="assetDetailsTitle">-</div>
                        <div class="asset-details-subtitle" id="assetDetailsSubtitle"></div>
                    </div>
                    <span class="asset-details-badge pending" id="assetDetailsBadge">Pending</span>
                </div>
                
                <!-- Processing Info (when asset is being generated) -->
                <div class="processing-info" id="processingInfo">
                    <div class="processing-spinner"></div>
                    <div class="processing-text">
                        <div class="processing-title" id="processingTitle">Generating...</div>
                        <div class="processing-detail" id="processingDetail">Processing with AI provider</div>
                    </div>
                </div>
                
                <div class="asset-properties" id="assetProperties"></div>
            </div>
            
            <!-- Prompt Box -->
            <div class="prompt-box hidden" id="promptBox">
                <div class="prompt-box-label">Generation Prompt</div>
                <div class="prompt-box-text" id="promptBoxText"></div>
            </div>
            
            <!-- History View -->
            <section class="history-view" id="historyView">
                <div id="historyContent"></div>
            </section>
            
            <!-- Future Step View -->
            <section class="future-step-view" id="futureStepView">
                <div class="future-step-icon" id="futureStepIcon">⏳</div>
                <h2 class="future-step-title" id="futureStepTitle">Step Name</h2>
                <p class="future-step-desc" id="futureStepDesc">This step will execute later in the pipeline.</p>
                <span class="future-step-badge">⏱ Not started yet</span>
            </section>
            
            <!-- Complete Section -->
            <section class="complete-section" id="completeSection">
                <div class="complete-icon">✓</div>
                <h2 class="complete-title">Pipeline Complete!</h2>
                <p class="complete-subtitle">All assets have been processed successfully.</p>
                <div class="results-summary">
                    <div class="result-item">
                        <div class="result-value" id="totalAssets">0</div>
                        <div class="result-label">Assets</div>
                    </div>
                    <div class="result-item">
                        <div class="result-value" id="totalSteps">0</div>
                        <div class="result-label">Steps</div>
                    </div>
                    <div class="result-item">
                        <div class="result-value" id="duration">0s</div>
                        <div class="result-label">Duration</div>
                    </div>
                </div>
                
                <!-- Saved Files Summary -->
                <div class="saved-files-summary" id="savedFilesSummary" style="display: none;">
                    <div class="saved-files-header">
                        <span class="saved-files-header-icon">💾</span>
                        Saved Files
                    </div>
                    <div class="saved-files-stats">
                        <div class="saved-stat">
                            <div class="saved-stat-value" id="savedFilesCount">0</div>
                            <div class="saved-stat-label">Files</div>
                        </div>
                        <div class="saved-stat">
                            <div class="saved-stat-value" id="savedFilesSize">0 KB</div>
                            <div class="saved-stat-label">Total Size</div>
                        </div>
                    </div>
                    <div class="saved-files-path">
                        <div class="saved-files-path-label">Cache Directory:</div>
                        <span id="savedCacheDir">.artgen/</span>
                    </div>
                    <div class="saved-files-steps" id="savedFilesSteps"></div>
                </div>
                
                <button class="btn btn-secondary" id="closeBtn">Close Window</button>
            </section>
            
            <!-- Empty State -->
            <div class="empty-state" id="emptyState">
                <div class="empty-state-icon">📋</div>
                <div class="empty-state-text">Select an asset to view details</div>
            </div>
        </main>
    </div>
    
    <!-- Queue Mode Overlay -->
    <div id="queueMode" class="queue-mode">
        <div class="queue-mode-header">
            <div class="queue-mode-title">
                <h2>📋 Review Queue</h2>
                <span class="queue-progress" id="queueProgress">0 of 0</span>
            </div>
            <button class="queue-mode-close" onclick="exitQueueMode()">
                <span>✕</span> Exit Queue
            </button>
        </div>
        <div class="queue-mode-content">
            <div class="queue-item-container" id="queueItemContainer">
                <!-- Queue items rendered here -->
            </div>
            <div class="queue-empty" id="queueEmpty" style="display: none;">
                <div class="queue-empty-icon">✓</div>
                <h3 class="queue-empty-title">Queue is empty</h3>
                <p class="queue-empty-text">No items need review right now. Nice work!</p>
                <button class="queue-btn-secondary" onclick="exitQueueMode()" style="margin-top: 24px;">Back to Pipeline</button>
            </div>
        </div>
    </div>
    
    <!-- Lightbox Modal -->
    <div id="lightbox" class="lightbox" onclick="closeLightboxOnBackdrop(event)">
        <button class="lightbox-close" onclick="closeLightbox()" title="Close (Esc)">&times;</button>
        <button class="lightbox-nav prev" onclick="lightboxPrev()" title="Previous">&#8249;</button>
        <button class="lightbox-nav next" onclick="lightboxNext()" title="Next">&#8250;</button>
        <div class="lightbox-content">
            <img id="lightboxImg" class="lightbox-img" src="" alt="Full size image" 
                 onmousedown="startDrag(event)" ondblclick="toggleZoom()">
        </div>
        <div class="lightbox-caption" id="lightboxCaption"></div>
        <div class="lightbox-controls">
            <button class="lightbox-btn" onclick="zoomOut()" title="Zoom Out">− Zoom Out</button>
            <span class="lightbox-zoom-level" id="zoomLevel">100%</span>
            <button class="lightbox-btn" onclick="zoomIn()" title="Zoom In">+ Zoom In</button>
            <button class="lightbox-btn" onclick="resetZoom()" title="Reset">Reset</button>
        </div>
    </div>
    
    <script>
        // ===== STATE =====
        let ws = null;
        let currentRequest = null;
        let startTime = null;
        let pipelineSteps = [];
        let assets = [];
        let selectedAssetId = null;
        let viewingStep = null; // null = current, otherwise step ID for history/future
        let viewingStepData = null; // cached data for viewed step
        let stepAssetStatus = {}; // { stepId: Set(['asset1', 'asset2']) } - which assets completed each step
        let currentStep = null;
        let currentStepType = null;
        let progressData = null;
        let pipelineComplete = false;
        
        // Queue state
        let queueItems = []; // Array of pending approval requests
        let queueIndex = 0; // Current position in queue
        let queueMode = false; // Whether queue mode is active
        
        // Provider descriptions
        const PROVIDER_DESCRIPTIONS = {
            'generate_image': 'Being generated by Gemini Imagen',
            'generate_sprite': 'Being generated by Gemini Imagen',
            'generate_text': 'Being generated by Gemini 2.5 Flash',
            'generate_name': 'Being generated by Gemini 2.5 Flash',
            'generate_prompt': 'Being generated by Gemini 2.5 Flash',
            'research': 'Researching with Gemini 2.5 Flash',
            'assess': 'Being assessed by Gemini Vision',
            'user_select': 'Awaiting user selection',
            'user_approve': 'Awaiting user approval',
        };
        
        const STEP_TYPE_ICONS = {
            'generate_image': '🎨', 'generate_sprite': '🎮', 'generate_text': '📝',
            'generate_name': '✏️', 'generate_prompt': '💬', 'research': '🔍',
            'assess': '🔬', 'user_select': '👆', 'user_approve': '✅',
            'refine': '✨', 'remove_background': '🖼️', 'resize': '📐',
        };
        
        // ===== ELEMENTS =====
        const $ = id => document.getElementById(id);
        const statusDot = $('statusDot');
        const statusText = $('statusText');
        const pipelineName = $('pipelineName');
        const progressPercent = $('progressPercent');
        const pipelineStepsRow = $('pipelineStepsRow');
        const stageSectionTitle = $('stageSectionTitle');
        const stageInfo = $('stageInfo');
        const stageIcon = $('stageIcon');
        const stageName = $('stageName');
        const stageType = $('stageType');
        const stageDesc = $('stageDesc');
        const stageStatusBadge = $('stageStatusBadge');
        const assetCount = $('assetCount');
        const assetList = $('assetList');
        const historyBanner = $('historyBanner');
        const historyBannerText = $('historyBannerText');
        const historyStepName = $('historyStepName');
        const assetDetails = $('assetDetails');
        const assetDetailsTitle = $('assetDetailsTitle');
        const assetDetailsSubtitle = $('assetDetailsSubtitle');
        const assetDetailsBadge = $('assetDetailsBadge');
        const processingInfo = $('processingInfo');
        const processingTitle = $('processingTitle');
        const processingDetail = $('processingDetail');
        const assetProperties = $('assetProperties');
        const promptBox = $('promptBox');
        const promptBoxText = $('promptBoxText');
        const approvalSection = $('approvalSection');
        const approvalTitle = $('approvalTitle');
        const approvalSubtitle = $('approvalSubtitle');
        const optionsGrid = $('optionsGrid');
        const historyView = $('historyView');
        const historyContent = $('historyContent');
        const futureStepView = $('futureStepView');
        const completeSection = $('completeSection');
        const emptyState = $('emptyState');
        const queueBtn = $('queueBtn');
        const queueBadge = $('queueBadge');
        const queueModeEl = $('queueMode');
        const queueProgress = $('queueProgress');
        const queueItemContainer = $('queueItemContainer');
        const queueEmpty = $('queueEmpty');
        
        // ===== WEBSOCKET =====
        function connect() {
            ws = new WebSocket(`ws://${window.location.host}/ws`);
            
            ws.onopen = () => {
                statusDot.className = 'status-dot';
                statusText.textContent = 'Connected';
            };
            
            ws.onclose = () => {
                statusDot.className = 'status-dot error';
                statusText.textContent = 'Disconnected';
                setTimeout(connect, 2000);
            };
            
            ws.onerror = () => {
                statusDot.className = 'status-dot error';
                statusText.textContent = 'Error';
            };
            
            ws.onmessage = (e) => {
                try {
                    const msg = JSON.parse(e.data);
                    if (msg.type === 'pong') return;
                    handleMessage(msg);
                } catch (err) {
                    console.error('Parse error:', err);
                }
            };
        }
        
        function handleMessage(msg) {
            switch (msg.type) {
                case 'connected':
                    if (msg.data.progress) updateProgress(msg.data.progress);
                    // Add all pending requests to queue
                    if (msg.data.pending?.length > 0) {
                        msg.data.pending.forEach(req => addToQueue(req));
                        showApproval(msg.data.pending[0]);
                    }
                    break;
                case 'progress':
                    updateProgress(msg.data);
                    break;
                case 'approval_request':
                    showApproval(msg.data);
                    break;
            }
        }
        
        // ===== PROGRESS =====
        function updateProgress(data) {
            progressData = data;
            if (!startTime && data.started_at) startTime = new Date(data.started_at);
            
            pipelineName.textContent = data.pipeline_name || 'Pipeline';
            progressPercent.textContent = `${data.percent || 0}%`;
            currentStep = data.current_step;
            currentStepType = data.current_step_type;
            
            // Update status
            if (data.phase === 'waiting') {
                statusDot.className = 'status-dot waiting';
                statusText.textContent = 'Waiting for input';
            } else if (data.phase === 'running') {
                statusDot.className = 'status-dot';
                statusText.textContent = 'Running';
                if (approvalSection.classList.contains('visible') && !currentRequest) {
                    approvalSection.classList.remove('visible');
                }
            } else if (data.phase === 'complete') {
                pipelineComplete = true;
                statusDot.className = 'status-dot';
                statusText.textContent = 'Complete';
            } else if (data.phase === 'failed') {
                statusDot.className = 'status-dot error';
                statusText.textContent = 'Failed';
            }
            
            // Update steps
            if (data.pipeline_steps?.length > 0) {
                const prevSteps = pipelineSteps;
                pipelineSteps = data.pipeline_steps;
                
                // Check if any steps just completed (for cache indicators)
                const newlyCompleted = pipelineSteps.some((step, i) => {
                    const prevStatus = prevSteps[i]?.status;
                    return (step.status === 'complete' || step.status === 'skipped') 
                        && prevStatus !== 'complete' && prevStatus !== 'skipped';
                });
                
                if (newlyCompleted || data.phase === 'complete') {
                    // Refresh cache indicators when steps complete
                    checkStepCaches();
                }
                
                renderPipelineSteps();
            }
            
            // Update assets with processing status
            if (data.assets?.length > 0) {
                const isRunning = data.phase === 'running';
                const currentStepId = data.current_step;
                
                assets = data.assets.map(a => ({
                    ...a,
                    // Store the original backend status
                    _backendStatus: a.status,
                }));
                
                // If running and we have a current step, fetch its asset status
                if (isRunning && currentStepId && !viewingStep) {
                    fetchStepAssetStatus(currentStepId).then(() => {
                        // Re-render after fetching step status
                        renderAssets();
                    });
                }
                
                renderAssets();
            }
            
            // Update stage info if viewing current
            if (viewingStep === null) {
                updateStageInfo(data);
                
                // Show prompt if available
                if (data.current_step_prompt) {
                    promptBox.classList.remove('hidden');
                    promptBoxText.textContent = data.current_step_prompt;
                }
            }
            
            // Update selected asset details if processing
            if (selectedAssetId) {
                const asset = assets.find(a => a.id === selectedAssetId);
                if (asset) {
                    updateAssetDetails(asset);
                }
            }
            
            // Auto-select first asset if none selected
            if (!selectedAssetId && assets.length > 0) {
                selectAsset(assets[0].id);
            }
        }
        
        // ===== RENDER PIPELINE STEPS =====
        // Track which steps have cached data
        let stepsWithCache = new Set();
        
        async function checkStepCaches() {
            // Check which steps have saved data
            for (const step of pipelineSteps) {
                if (step.status === 'complete' || step.status === 'skipped') {
                    try {
                        const resp = await fetch(`/api/step/${step.id}/asset-status`);
                        if (resp.ok) {
                            const data = await resp.json();
                            if (data.completed_assets?.length > 0) {
                                stepsWithCache.add(step.id);
                            }
                        }
                    } catch (e) {
                        // Ignore errors
                    }
                }
            }
            renderPipelineSteps();
        }
        
        function renderPipelineSteps() {
            const icons = { pending: '○', running: '●', complete: '✓', failed: '✕', skipped: '−' };
            let html = '';
            
            pipelineSteps.forEach((step, i) => {
                const isActive = step.status === 'running';
                const isViewing = viewingStep === step.id;
                const isComplete = step.status === 'complete' || step.status === 'skipped';
                const isPending = step.status === 'pending';
                const hasCachedData = stepsWithCache.has(step.id);
                
                if (i > 0) {
                    const prevComplete = pipelineSteps[i-1].status === 'complete' || pipelineSteps[i-1].status === 'skipped';
                    const connectorClass = prevComplete ? 'complete' : '';
                    html += `<div class="step-connector ${connectorClass}"></div>`;
                }
                
                const saveIndicator = hasCachedData ? '<span class="step-chip-save" title="Has saved data">💾</span>' : '';
                
                html += `
                    <div class="pipeline-step-chip ${isActive ? 'active' : ''} ${isComplete ? 'complete' : ''} ${isPending ? 'pending' : ''} ${isViewing ? 'viewing' : ''}"
                         onclick="viewStep('${step.id}')"
                         title="${step.description || step.id}${hasCachedData ? ' (saved)' : ''}">
                        <div class="step-chip-icon ${step.status}">${icons[step.status] || '○'}</div>
                        <span>${step.id}</span>${saveIndicator}
                    </div>
                `;
            });
            
            // Add Fin step (always at end)
            const allComplete = pipelineSteps.every(s => s.status === 'complete' || s.status === 'skipped');
            if (pipelineSteps.length > 0) {
                const lastStepComplete = pipelineSteps[pipelineSteps.length - 1].status === 'complete' || pipelineSteps[pipelineSteps.length - 1].status === 'skipped';
                html += `<div class="step-connector ${lastStepComplete ? 'complete' : ''}"></div>`;
            }
            
            const finActive = viewingStep === '_fin';
            const finEnabled = pipelineComplete || allComplete;
            html += `
                <div class="pipeline-step-chip ${finEnabled ? 'fin-step' : 'pending'} ${finActive ? 'viewing' : ''}"
                     onclick="${finEnabled ? "viewFinStep()" : ''}"
                     title="Pipeline completion summary">
                    <div class="step-chip-icon ${finEnabled ? 'complete' : 'pending'}">${finEnabled ? '🏁' : '○'}</div>
                    <span>Fin</span>
                </div>
            `;
            
            pipelineStepsRow.innerHTML = html;
        }
        
        // ===== RENDER ASSETS =====
        function renderAssets() {
            assetCount.textContent = `(${assets.length})`;
            
            if (assets.length === 0) {
                assetList.innerHTML = '<div class="empty-state" style="padding: 20px;"><div style="font-size: 13px;">No assets loaded</div></div>';
                return;
            }
            
            assetList.innerHTML = assets.map(asset => {
                // Use shared function for consistent status
                const effectiveStatus = getEffectiveAssetStatus(asset);
                const needsReview = effectiveStatus === 'needs-review';
                const isProcessing = effectiveStatus === 'processing';
                
                let statusContent;
                if (needsReview) {
                    // Warning triangle for needs review
                    statusContent = '<div class="asset-warning"></div>';
                } else if (isProcessing) {
                    // Spinner for processing
                    statusContent = '<div class="asset-spinner"></div>';
                } else {
                    // Standard status icon based on effective status
                    statusContent = `<div class="asset-status ${effectiveStatus}">${{pending: '○', complete: '✓', failed: '✕'}[effectiveStatus] || '○'}</div>`;
                }
                
                const itemClass = needsReview ? 'needs-review' : effectiveStatus;
                
                return `
                    <div class="asset-item ${asset.id === selectedAssetId ? 'selected' : ''} ${itemClass}"
                         onclick="selectAsset('${asset.id}')">
                        ${statusContent}
                        <span class="asset-name" title="${asset.name}">${asset.name}</span>
                    </div>
                `;
            }).join('');
        }
        
        // ===== SELECT ASSET =====
        function selectAsset(assetId) {
            selectedAssetId = assetId;
            renderAssets();
            
            const asset = assets.find(a => a.id === assetId);
            if (!asset) return;
            
            updateAssetDetails(asset);
            
            // If viewing a step's history (completed step), re-fetch filtered to this asset
            if (viewingStep && (viewingStepData?.status === 'complete' || viewingStepData?.status === 'skipped')) {
                fetchStepHistory(viewingStep, assetId);
            }
            // If in live view and this asset has completed the current step, show its output
            else if (!viewingStep && currentStep && progressData?.phase === 'running') {
                const currentStepCompleted = stepAssetStatus[currentStep];
                if (currentStepCompleted && currentStepCompleted.has(assetId)) {
                    // Asset has finished this step - show its output
                    showAssetStepOutput(currentStep, assetId, asset);
                }
            }
        }
        
        async function showAssetStepOutput(stepId, assetId, asset) {
            // Show the output for an asset that has completed the current step
            try {
                const resp = await fetch(`/api/history/${stepId}?asset_id=${encodeURIComponent(assetId)}`);
                if (resp.ok) {
                    const data = await resp.json();
                    
                    // Show output in the asset details area
                    let outputHtml = '<div class="asset-step-output">';
                    outputHtml += `<div class="output-header">✓ Completed: ${stepId}</div>`;
                    
                    // Show any generated images
                    if (data.files && data.files.length > 0) {
                        outputHtml += '<div class="output-images history-images">';
                        data.files.forEach((file, i) => {
                            outputHtml += `<img src="/files/${file}" alt="Generated ${i+1}" class="output-thumbnail">`;
                        });
                        outputHtml += '</div>';
                    }
                    
                    // Show text outputs
                    data.outputs.forEach(output => {
                        const outputData = output.data;
                        if (outputData?.content) {
                            outputHtml += `<div class="output-text">${outputData.content}</div>`;
                        }
                        if (outputData?.assessment) {
                            outputHtml += `<div class="output-assessment">${outputData.assessment}</div>`;
                        }
                    });
                    
                    // Show saved path (compact version)
                    if (data.saved_paths && data.saved_paths.length > 0) {
                        const cachePath = data.saved_paths[0];
                        outputHtml += `
                            <div class="saved-path-info compact">
                                <span class="saved-path-icon">💾</span>
                                <div class="saved-path-text">
                                    <div class="saved-path-value">${cachePath}</div>
                                </div>
                            </div>
                        `;
                    }
                    
                    outputHtml += '</div>';
                    
                    // Append to asset properties area
                    const outputContainer = document.getElementById('assetStepOutput');
                    if (outputContainer) {
                        outputContainer.innerHTML = outputHtml;
                    } else {
                        // Create container if it doesn't exist
                        assetProperties.insertAdjacentHTML('afterend', `<div id="assetStepOutput">${outputHtml}</div>`);
                    }
                }
            } catch (e) {
                console.error('Failed to fetch asset step output:', e);
            }
        }
        
        function getEffectiveAssetStatus(asset) {
            // Compute effective status using same logic as renderAssets
            const needsReviewAssetId = currentRequest ? currentRequest.asset_id : null;
            const stepToCheck = viewingStep || currentStep;
            const stepCompleted = stepToCheck && stepAssetStatus[stepToCheck] 
                ? stepAssetStatus[stepToCheck] 
                : null;
            const isViewingFutureStep = viewingStepData && viewingStepData.status === 'pending';
            const isLiveView = !viewingStep && progressData?.phase === 'running';
            
            if (asset.id === needsReviewAssetId) {
                return 'needs-review';
            } else if (isViewingFutureStep) {
                return 'pending';
            } else if (isLiveView && currentStep) {
                if (progressData?.current_asset === asset.name) {
                    return 'processing';
                } else if (stepCompleted && stepCompleted.has(asset.id)) {
                    return 'complete';
                } else {
                    return 'pending';
                }
            } else if (stepCompleted) {
                return stepCompleted.has(asset.id) ? 'complete' : 'pending';
            } else {
                return asset._backendStatus || asset.status || 'pending';
            }
        }
        
        function updateAssetDetails(asset) {
            emptyState.style.display = 'none';
            assetDetails.classList.remove('hidden');
            assetDetailsTitle.textContent = asset.name;
            
            // Get effective status (same logic as asset list)
            const effectiveStatus = getEffectiveAssetStatus(asset);
            
            // Update badge
            assetDetailsBadge.className = `asset-details-badge ${effectiveStatus}`;
            const statusLabels = { pending: 'Pending', processing: 'Processing', complete: 'Complete', failed: 'Failed', 'needs-review': 'Needs Review' };
            assetDetailsBadge.textContent = statusLabels[effectiveStatus] || 'Unknown';
            
            // Show processing info if asset is being processed
            if (effectiveStatus === 'processing' && currentStepType) {
                processingInfo.classList.add('visible');
                processingTitle.textContent = 'Generating...';
                processingDetail.textContent = PROVIDER_DESCRIPTIONS[currentStepType] || 'Processing with AI provider';
                assetDetailsSubtitle.textContent = `Currently at: ${currentStep || 'processing'}`;
            } else {
                processingInfo.classList.remove('visible');
                assetDetailsSubtitle.textContent = viewingStep ? `Viewing: ${viewingStep}` : '';
            }
            
            // Show properties
            const props = Object.entries(asset.data || {}).filter(([k]) => k !== 'id');
            assetProperties.innerHTML = props.map(([key, value]) => `
                <div class="asset-prop">
                    <div class="asset-prop-label">${key}</div>
                    <div class="asset-prop-value">${typeof value === 'object' ? JSON.stringify(value) : value}</div>
                </div>
            `).join('');
            
            // Clear previous step output (will be re-populated by selectAsset if needed)
            const outputContainer = document.getElementById('assetStepOutput');
            if (outputContainer) {
                outputContainer.innerHTML = '';
            }
        }
        
        // ===== UPDATE STAGE INFO =====
        function updateStageInfo(data) {
            stageSectionTitle.textContent = 'Current Stage';
            stageInfo.classList.remove('future-stage');
            stageStatusBadge.style.display = 'none';
            
            stageIcon.textContent = STEP_TYPE_ICONS[data.current_step_type] || '▶';
            stageName.textContent = data.current_step || '-';
            stageType.textContent = data.current_step_type || '-';
            stageDesc.textContent = data.current_step_description || data.message || 'Processing...';
        }
        
        // ===== VIEW STEP (HISTORY OR FUTURE) =====
        async function viewStep(stepId) {
            const step = pipelineSteps.find(s => s.id === stepId);
            if (!step) return;
            
            viewingStep = stepId;
            viewingStepData = step;
            
            // Hide other sections
            approvalSection.classList.remove('visible');
            promptBox.classList.add('hidden');
            completeSection.classList.remove('visible');
            futureStepView.classList.remove('visible');
            historyView.classList.remove('visible');
            
            // Fetch step-specific asset status if viewing a completed step
            if (step.status === 'complete' || step.status === 'skipped') {
                await fetchStepAssetStatus(stepId);
            }
            
            renderPipelineSteps();
            renderAssets(); // Re-render with step-specific status
            
            // Update sidebar stage info
            updateStageInfoForStep(step);
            
            if (step.status === 'complete' || step.status === 'skipped') {
                // Show history
                historyBanner.classList.add('visible');
                historyBanner.classList.remove('future');
                historyBannerText.innerHTML = `Viewing history for step: <strong>${stepId}</strong>`;
                historyStepName.textContent = stepId;
                
                historyView.classList.add('visible');
                // Auto-select first asset if none selected
                if (!selectedAssetId && assets.length > 0) {
                    selectedAssetId = assets[0].id;
                    renderAssets();
                }
                fetchStepHistory(stepId, selectedAssetId);
            } else if (step.status === 'pending') {
                // Show future step info
                historyBanner.classList.add('visible');
                historyBanner.classList.add('future');
                historyBannerText.innerHTML = `Previewing future step: <strong>${stepId}</strong>`;
                historyStepName.textContent = stepId;
                
                showFutureStep(step);
            } else if (step.status === 'running') {
                // Go back to current
                backToCurrent();
            }
        }
        
        async function fetchStepAssetStatus(stepId) {
            try {
                const resp = await fetch(`/api/step/${stepId}/asset-status`);
                if (resp.ok) {
                    const data = await resp.json();
                    stepAssetStatus[stepId] = new Set(data.completed_assets || []);
                }
            } catch (e) {
                console.error('Failed to fetch step asset status:', e);
            }
        }
        
        function updateStageInfoForStep(step) {
            const isPending = step.status === 'pending';
            const isComplete = step.status === 'complete' || step.status === 'skipped';
            const hasCachedData = stepsWithCache.has(step.id);
            
            stageSectionTitle.textContent = isPending ? 'Future Stage' : (isComplete ? 'Completed Stage' : 'Current Stage');
            stageInfo.classList.toggle('future-stage', isPending);
            
            stageIcon.textContent = STEP_TYPE_ICONS[step.type] || '▶';
            stageName.textContent = step.id;
            stageType.textContent = step.type;
            
            let descText = step.description || `This step will ${step.for_each === 'asset' ? 'process each asset' : 'run globally'}`;
            if (isComplete && hasCachedData) {
                descText += ` 💾 Data saved to .artgen/${step.id}/`;
            }
            stageDesc.textContent = descText;
            
            if (isPending) {
                stageStatusBadge.style.display = 'inline-flex';
                stageStatusBadge.className = 'stage-status-badge not-started';
                stageStatusBadge.textContent = '⏱ Not started yet';
            } else if (isComplete) {
                stageStatusBadge.style.display = 'inline-flex';
                stageStatusBadge.className = 'stage-status-badge complete';
                stageStatusBadge.textContent = hasCachedData ? '✓ Completed & Saved' : '✓ Completed';
            } else {
                stageStatusBadge.style.display = 'none';
            }
        }
        
        function showFutureStep(step) {
            futureStepView.classList.add('visible');
            
            $('futureStepIcon').textContent = STEP_TYPE_ICONS[step.type] || '⏳';
            $('futureStepTitle').textContent = step.id;
            
            let desc = step.description || '';
            if (!desc) {
                const forEachText = step.for_each === 'asset' ? 'for each asset' : 'globally';
                desc = `This step will execute ${forEachText} when the pipeline reaches it.`;
            }
            $('futureStepDesc').textContent = desc;
        }
        
        async function fetchStepHistory(stepId, assetId = null) {
            try {
                let url = `/api/history/${stepId}`;
                if (assetId) {
                    url += `?asset_id=${encodeURIComponent(assetId)}`;
                }
                const resp = await fetch(url);
                if (resp.ok) {
                    const data = await resp.json();
                    renderHistory(data, assetId);
                } else {
                    historyContent.innerHTML = '<div class="empty-state"><div class="empty-state-text">No history available</div></div>';
                }
            } catch (e) {
                historyContent.innerHTML = '<div class="empty-state"><div class="empty-state-text">Failed to load history</div></div>';
            }
        }
        
        function renderHistory(data, assetId = null) {
            let html = '';
            
            // Show which asset we're viewing
            if (assetId) {
                const asset = assets.find(a => a.id === assetId);
                const assetName = asset ? asset.name : assetId;
                html += `<div class="history-asset-header">
                    <span class="history-asset-label">Showing results for:</span>
                    <strong>${assetName}</strong>
                </div>`;
            }
            
            // Show text outputs with enhanced display for verdicts/assessments
            data.outputs.forEach(output => {
                const outputData = output.data;
                if (!outputData) return;
                
                // Check for assessment/verdict data
                const isVerdict = outputData.assessment || outputData.verdict || outputData.approved !== undefined;
                const verdictClass = isVerdict ? 'verdict' : '';
                
                // Handle different output structures
                if (typeof outputData === 'object') {
                    // Assessment results
                    if (outputData.assessment) {
                        html += `
                            <div class="history-output verdict">
                                <div class="history-output-label">🔬 AI Assessment</div>
                                <div class="history-output-content">${outputData.assessment}</div>
                            </div>
                        `;
                        if (outputData.approved !== undefined) {
                            html += `
                                <div class="history-output ${outputData.approved ? 'verdict' : ''}">
                                    <div class="history-output-label">Verdict</div>
                                    <div class="history-output-content">${outputData.approved ? '✅ Approved' : '❌ Rejected'}</div>
                                </div>
                            `;
                        }
                    }
                    // Text content
                    else if (outputData.content) {
                        html += `
                            <div class="history-output ${verdictClass}">
                                <div class="history-output-label">Output</div>
                                <div class="history-output-content">${outputData.content}</div>
                            </div>
                        `;
                    }
                    // Selection info
                    if (output.selected_index !== null && output.selected_index !== undefined) {
                        html += `
                            <div class="history-output">
                                <div class="history-output-label">User Selection</div>
                                <div class="history-output-content">Selected option ${output.selected_index + 1}</div>
                            </div>
                        `;
                    }
                } else if (typeof outputData === 'string') {
                    html += `
                        <div class="history-output">
                            <div class="history-output-label">Output</div>
                            <div class="history-output-content">${outputData}</div>
                        </div>
                    `;
                }
            });
            
            // Show images with selection highlighting
            if (data.files.length > 0) {
                html += '<div class="history-output-label" style="margin: 16px 0 12px;">Generated Images</div>';
                html += '<div class="history-images">';
                
                // Find selected index from outputs
                let selectedIdx = null;
                data.outputs.forEach(o => {
                    if (o.selected_index !== null && o.selected_index !== undefined) {
                        selectedIdx = o.selected_index;
                    }
                });
                
                data.files.forEach((file, i) => {
                    const isSelected = selectedIdx !== null && file.includes(`v${selectedIdx + 1}`);
                    html += `
                        <div class="history-image-card ${isSelected ? 'was-selected' : ''}">
                            <img src="/files/${file}" alt="Generated ${i+1}">
                            <div class="history-image-label">${isSelected ? '✓ Selected' : file.split('/').pop()}</div>
                        </div>
                    `;
                });
                html += '</div>';
            }
            
            // Show saved path info
            if (data.cache_dir || (data.saved_paths && data.saved_paths.length > 0)) {
                const displayPath = assetId && data.saved_paths?.length > 0 
                    ? data.saved_paths[0] 
                    : data.cache_dir;
                
                if (displayPath) {
                    html += `
                        <div class="saved-path-info compact">
                            <span class="saved-path-icon">💾</span>
                            <div class="saved-path-text">
                                <div class="saved-path-label">Saved to:</div>
                                <div class="saved-path-value">${displayPath}</div>
                            </div>
                            <button class="saved-path-copy" onclick="copyToClipboard('${displayPath}')" title="Copy path">
                                📋 Copy
                            </button>
                        </div>
                    `;
                }
            }
            
            if (!html || (data.outputs.length === 0 && data.files.length === 0)) {
                if (assetId) {
                    html = '<div class="empty-state"><div class="empty-state-text">No outputs recorded for this asset at this step</div></div>';
                } else {
                    html = '<div class="empty-state"><div class="empty-state-text">No outputs recorded for this step</div></div>';
                }
            }
            
            historyContent.innerHTML = html;
        }
        
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(() => {
                // Brief visual feedback could be added here
            }).catch(err => {
                console.error('Copy failed:', err);
            });
        }
        
        async function viewFinStep() {
            viewingStep = '_fin';
            
            // Hide other sections
            approvalSection.classList.remove('visible');
            promptBox.classList.add('hidden');
            historyView.classList.remove('visible');
            futureStepView.classList.remove('visible');
            assetDetails.classList.add('hidden');
            emptyState.style.display = 'none';
            
            // Update banner
            historyBanner.classList.add('visible');
            historyBanner.classList.remove('future');
            historyBannerText.innerHTML = `<strong>Pipeline Summary</strong>`;
            
            // Update sidebar
            stageSectionTitle.textContent = 'Completion';
            stageInfo.classList.remove('future-stage');
            stageIcon.textContent = '🏁';
            stageName.textContent = 'Finished';
            stageType.textContent = 'summary';
            stageDesc.textContent = 'All pipeline steps have completed.';
            stageStatusBadge.style.display = 'inline-flex';
            stageStatusBadge.className = 'stage-status-badge complete';
            stageStatusBadge.textContent = '✓ Complete';
            
            // Ensure cache indicators are up to date
            await checkStepCaches();
            renderPipelineSteps();
            showComplete(progressData || {});
        }
        
        async function backToCurrent() {
            viewingStep = null;
            viewingStepData = null;
            historyBanner.classList.remove('visible');
            historyView.classList.remove('visible');
            futureStepView.classList.remove('visible');
            completeSection.classList.remove('visible');
            stageStatusBadge.style.display = 'none';
            stageInfo.classList.remove('future-stage');
            
            renderPipelineSteps();
            
            // Fetch current step's asset status for accurate display
            if (currentStep && progressData?.phase === 'running') {
                await fetchStepAssetStatus(currentStep);
            }
            
            renderAssets(); // Re-render with current step status
            
            if (progressData) {
                updateProgress(progressData);
                if (currentRequest) {
                    showApproval(currentRequest);
                }
            }
            
            // Re-show asset details
            if (selectedAssetId) {
                const asset = assets.find(a => a.id === selectedAssetId);
                if (asset) {
                    updateAssetDetails(asset);
                }
            }
        }
        
        // ===== APPROVAL =====
        function showApproval(request) {
            currentRequest = request;
            
            // Add to queue if not already there
            addToQueue(request);
            
            // Re-render assets to show warning icon
            renderAssets();
            
            if (viewingStep !== null) return; // Don't show if viewing history/future
            
            emptyState.style.display = 'none';
            approvalSection.classList.add('visible');
            
            const isSelect = request.type === 'select_one';
            approvalTitle.textContent = isSelect 
                ? `Select best option for "${request.asset_name}"`
                : `Approve result for "${request.asset_name}"?`;
            approvalSubtitle.textContent = isSelect
                ? 'Click on an option to select it'
                : 'Click the image to approve';
            
            // Render options
            optionsGrid.innerHTML = '';
            request.options.forEach((opt, i) => {
                const card = document.createElement('div');
                card.className = 'option-card';
                
                if (opt.path || opt.image_path) {
                    const imgPath = opt.path || opt.image_path;
                    card.innerHTML = `
                        <div class="click-hint">Click to ${isSelect ? 'select' : 'approve'}</div>
                        <img class="option-image" src="/files/${imgPath}" alt="Option ${i+1}">
                        <div class="option-content">
                            <span class="option-number">${i+1}</span>
                            <span class="option-label">${isSelect ? `Option ${i+1}` : 'Result'}</span>
                        </div>
                    `;
                } else if (opt.text || opt.content) {
                    card.innerHTML = `
                        <div class="click-hint">Click to ${isSelect ? 'select' : 'approve'}</div>
                        <div class="option-text">${opt.text || opt.content}</div>
                        <div class="option-content">
                            <span class="option-number">${i+1}</span>
                            <span class="option-label">${isSelect ? `Option ${i+1}` : 'Result'}</span>
                        </div>
                    `;
                }
                
                card.onclick = () => selectAndSubmit(i);
                optionsGrid.appendChild(card);
            });
            
            $('regenerateBtn').textContent = request.type === 'approve' ? 'Reject & Regenerate' : 'Regenerate All';
        }
        
        async function selectAndSubmit(index) {
            if (!currentRequest) return;
            
            document.querySelectorAll('.option-card').forEach((c, i) => {
                c.classList.toggle('selected', i === index);
            });
            
            await new Promise(r => setTimeout(r, 150));
            
            const requestId = currentRequest.id;
            
            try {
                const resp = await fetch('/api/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        request_id: requestId,
                        approved: true,
                        selected_index: index,
                        regenerate: false,
                    }),
                });
                
                if (resp.ok) {
                    approvalSection.classList.remove('visible');
                    currentRequest = null;
                    removeFromQueue(requestId); // Remove from queue
                    renderAssets(); // Re-render to remove warning icon
                }
            } catch (e) {
                console.error('Submit failed:', e);
            }
        }
        
        async function submitRegenerate() {
            if (!currentRequest) return;
            
            const requestId = currentRequest.id;
            
            try {
                const resp = await fetch('/api/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        request_id: requestId,
                        approved: false,
                        regenerate: true,
                    }),
                });
                
                if (resp.ok) {
                    approvalSection.classList.remove('visible');
                    currentRequest = null;
                    removeFromQueue(requestId); // Remove from queue
                    renderAssets(); // Re-render to remove warning icon
                }
            } catch (e) {
                console.error('Regenerate failed:', e);
            }
        }
        
        // ===== QUEUE MODE =====
        function updateQueueBadge() {
            const count = queueItems.length;
            queueBadge.textContent = count;
            queueBadge.classList.toggle('empty', count === 0);
            queueBtn.classList.toggle('has-items', count > 0);
        }
        
        function addToQueue(request) {
            // Don't add duplicates
            if (!queueItems.find(q => q.id === request.id)) {
                queueItems.push(request);
                updateQueueBadge();
                
                // If in queue mode, refresh display
                if (queueMode) {
                    renderQueueItem();
                }
            }
        }
        
        function removeFromQueue(requestId) {
            const idx = queueItems.findIndex(q => q.id === requestId);
            if (idx !== -1) {
                queueItems.splice(idx, 1);
                // Adjust index if needed
                if (queueIndex >= queueItems.length) {
                    queueIndex = Math.max(0, queueItems.length - 1);
                }
                updateQueueBadge();
                
                // If in queue mode, refresh or show empty
                if (queueMode) {
                    renderQueueItem();
                }
            }
        }
        
        function enterQueueMode() {
            queueMode = true;
            queueIndex = 0;
            queueModeEl.classList.add('visible');
            document.body.style.overflow = 'hidden';
            renderQueueItem();
        }
        
        function exitQueueMode() {
            queueMode = false;
            queueModeEl.classList.remove('visible');
            document.body.style.overflow = '';
        }
        
        function renderQueueItem() {
            if (queueItems.length === 0) {
                queueItemContainer.style.display = 'none';
                queueEmpty.style.display = 'block';
                queueProgress.textContent = '0 of 0';
                return;
            }
            
            queueItemContainer.style.display = 'block';
            queueEmpty.style.display = 'none';
            queueProgress.textContent = `${queueIndex + 1} of ${queueItems.length}`;
            
            const request = queueItems[queueIndex];
            const isSelect = request.type === 'select_one' && request.options.length > 1;
            const isApproval = !isSelect; // Single option = approval mode
            
            let html = `
                <div class="queue-item-header">
                    <div class="queue-item-asset">${request.step_id || 'Step'}</div>
                    <h2 class="queue-item-title">${isSelect ? 'Select Best Option' : 'Approve Result'}</h2>
                    <p class="queue-item-subtitle">${request.asset_name || 'Asset'}</p>
                </div>
            `;
            
            // Build image data for lightbox
            const imageOptions = request.options
                .map((opt, i) => ({ path: opt.path || opt.image_path, index: i }))
                .filter(o => o.path);
            
            // Store image data for lightbox
            window._queueImageOptions = imageOptions;
            
            if (isApproval) {
                // Approval mode: centered single item with Accept/Reject
                const opt = request.options[0];
                const imgPath = opt?.path || opt?.image_path;
                const textContent = opt?.text || opt?.content;
                
                html += '<div class="queue-approval-layout">';
                
                if (imgPath) {
                    html += `
                        <div class="queue-approval-preview">
                            <img class="queue-approval-image" src="/files/${imgPath}" alt="Result"
                                 onclick="openQueueLightbox(0)">
                        </div>
                    `;
                } else if (textContent) {
                    html += `
                        <div class="queue-approval-preview">
                            <div class="queue-approval-text">${textContent}</div>
                        </div>
                    `;
                }
                
                html += `
                    <div class="queue-approval-actions">
                        <button class="queue-approve-btn accept" onclick="queueSelectOption(0)">
                            <span class="queue-approve-icon">✓</span>
                            <span class="queue-approve-label">Accept</span>
                            <span class="queue-approve-keys"><kbd>1</kbd> or <kbd>Y</kbd></span>
                        </button>
                        <button class="queue-approve-btn reject" onclick="queueRegenerate()">
                            <span class="queue-approve-icon">✕</span>
                            <span class="queue-approve-label">Reject</span>
                            <span class="queue-approve-keys"><kbd>2</kbd> or <kbd>N</kbd></span>
                        </button>
                    </div>
                </div>
                <div class="queue-actions" style="justify-content: center;">
                    <button class="queue-btn-skip" onclick="queueSkip()" ${queueItems.length <= 1 ? 'disabled' : ''}>
                        Skip for now →
                    </button>
                </div>
                <div class="queue-shortcuts">
                    <kbd>1</kbd> / <kbd>Y</kbd> accept &bull; 
                    <kbd>2</kbd> / <kbd>N</kbd> reject &bull; 
                    <kbd>Tab</kbd> skip &bull; 
                    <kbd>Esc</kbd> exit queue
                </div>
                `;
            } else {
                // Selection mode: grid of options
                html += '<div class="queue-options-grid">';
                
                request.options.forEach((opt, i) => {
                    if (opt.path || opt.image_path) {
                        const imgPath = opt.path || opt.image_path;
                        const imgIndex = imageOptions.findIndex(o => o.index === i);
                        html += `
                            <div class="queue-option-card" onclick="queueSelectOption(${i})" data-index="${i}">
                                <img class="queue-option-image" src="/files/${imgPath}" alt="Option ${i+1}" 
                                     onclick="event.stopPropagation(); openQueueLightbox(${imgIndex})">
                                <div class="queue-option-footer">
                                    <span class="queue-option-number">${i+1}</span>
                                    <span class="queue-option-label">Option ${i+1}</span>
                                </div>
                            </div>
                        `;
                    } else if (opt.text || opt.content) {
                        html += `
                            <div class="queue-option-card" onclick="queueSelectOption(${i})" data-index="${i}">
                                <div class="queue-option-text">${opt.text || opt.content}</div>
                                <div class="queue-option-footer">
                                    <span class="queue-option-number">${i+1}</span>
                                    <span class="queue-option-label">Option ${i+1}</span>
                                </div>
                            </div>
                        `;
                    }
                });
                
                html += `
                </div>
                <div class="queue-actions">
                    <button class="queue-btn-secondary" onclick="queueRegenerate()">Regenerate All</button>
                    <button class="queue-btn-skip" onclick="queueSkip()" ${queueItems.length <= 1 ? 'disabled' : ''}>
                        Skip for now →
                    </button>
                </div>
                <div class="queue-shortcuts">
                    <kbd>1</kbd>-<kbd>9</kbd> select option &bull; 
                    <kbd>R</kbd> regenerate &bull; 
                    <kbd>Tab</kbd> skip &bull; 
                    <kbd>Esc</kbd> exit queue
                </div>
                `;
            }
            
            queueItemContainer.innerHTML = html;
        }
        
        async function queueSelectOption(index) {
            if (queueItems.length === 0) return;
            const request = queueItems[queueIndex];
            
            // Visual feedback
            document.querySelectorAll('.queue-option-card').forEach((c, i) => {
                c.classList.toggle('selected', i === index);
            });
            
            await new Promise(r => setTimeout(r, 200));
            
            try {
                const resp = await fetch('/api/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        request_id: request.id,
                        approved: true,
                        selected_index: index,
                        regenerate: false,
                    }),
                });
                
                if (resp.ok) {
                    // Also update the main UI state
                    if (currentRequest?.id === request.id) {
                        approvalSection.classList.remove('visible');
                        currentRequest = null;
                    }
                    
                    removeFromQueue(request.id);
                    renderAssets();
                }
            } catch (e) {
                console.error('Queue select failed:', e);
            }
        }
        
        async function queueRegenerate() {
            if (queueItems.length === 0) return;
            const request = queueItems[queueIndex];
            
            try {
                const resp = await fetch('/api/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        request_id: request.id,
                        approved: false,
                        regenerate: true,
                    }),
                });
                
                if (resp.ok) {
                    // Also update the main UI state
                    if (currentRequest?.id === request.id) {
                        approvalSection.classList.remove('visible');
                        currentRequest = null;
                    }
                    
                    removeFromQueue(request.id);
                    renderAssets();
                }
            } catch (e) {
                console.error('Queue regenerate failed:', e);
            }
        }
        
        function queueSkip() {
            if (queueItems.length <= 1) return;
            
            // Move current item to end of queue
            const skipped = queueItems.splice(queueIndex, 1)[0];
            queueItems.push(skipped);
            
            // Stay at same index (which now shows the next item)
            if (queueIndex >= queueItems.length) {
                queueIndex = 0;
            }
            
            renderQueueItem();
        }
        
        function queueNext() {
            if (queueIndex < queueItems.length - 1) {
                queueIndex++;
                renderQueueItem();
            }
        }
        
        function queuePrev() {
            if (queueIndex > 0) {
                queueIndex--;
                renderQueueItem();
            }
        }
        
        function openQueueLightbox(imageIndex) {
            const imageOptions = window._queueImageOptions || [];
            if (imageOptions.length === 0) return;
            
            const images = imageOptions.map((opt, i) => ({
                src: `/files/${opt.path}`,
                caption: `Option ${opt.index + 1} of ${imageOptions.length}`
            }));
            
            openLightbox(images[imageIndex].src, images[imageIndex].caption, images, imageIndex);
        }
        
        // ===== COMPLETE =====
        async function showComplete(data) {
            completeSection.classList.add('visible');
            
            $('totalAssets').textContent = data.total_assets || assets.length || 0;
            $('totalSteps').textContent = data.total_steps || pipelineSteps.length || 0;
            
            if (startTime) {
                const elapsed = Math.floor((Date.now() - startTime.getTime()) / 1000);
                $('duration').textContent = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed/60)}m ${elapsed%60}s`;
            }
            
            // Fetch and display saved files summary
            try {
                const resp = await fetch('/api/saved-files');
                if (resp.ok) {
                    const savedData = await resp.json();
                    
                    if (savedData.total_files > 0) {
                        $('savedFilesSummary').style.display = 'block';
                        $('savedFilesCount').textContent = savedData.total_files;
                        $('savedFilesSize').textContent = savedData.total_size_formatted;
                        $('savedCacheDir').textContent = savedData.cache_dir || '.artgen/';
                        
                        // Show per-step breakdown
                        let stepsHtml = '';
                        savedData.steps.forEach(step => {
                            stepsHtml += `
                                <div class="saved-step-item">
                                    <span class="saved-step-name">${step.step_id}</span>
                                    <span class="saved-step-count">${step.file_count} files</span>
                                </div>
                            `;
                        });
                        $('savedFilesSteps').innerHTML = stepsHtml;
                    }
                }
            } catch (e) {
                console.error('Failed to fetch saved files:', e);
            }
        }
        
        async function closeAndShutdown() {
            try { await fetch('/api/shutdown', { method: 'POST' }); } catch {}
            window.close();
        }
        
        // ===== EVENT LISTENERS =====
        $('regenerateBtn').onclick = submitRegenerate;
        $('closeBtn').onclick = closeAndShutdown;
        $('backToCurrentBtn').onclick = backToCurrent;
        
        document.addEventListener('keydown', (e) => {
            // Queue mode keyboard shortcuts
            if (queueMode) {
                if (e.key === 'Escape') {
                    exitQueueMode();
                    return;
                }
                if (e.key === 'Tab') {
                    e.preventDefault();
                    queueSkip();
                    return;
                }
                if (queueItems.length > 0) {
                    const request = queueItems[queueIndex];
                    const isApproval = request.options.length === 1;
                    
                    if (isApproval) {
                        // Approval mode: 1/Y = accept, 2/N = reject
                        if (e.key === '1' || e.key.toLowerCase() === 'y') {
                            queueSelectOption(0);
                            return;
                        }
                        if (e.key === '2' || e.key.toLowerCase() === 'n') {
                            queueRegenerate();
                            return;
                        }
                    } else {
                        // Selection mode: 1-9 to select, R to regenerate
                        const num = parseInt(e.key);
                        if (num >= 1 && num <= request.options?.length) {
                            queueSelectOption(num - 1);
                            return;
                        }
                        if (e.key.toLowerCase() === 'r') {
                            queueRegenerate();
                            return;
                        }
                    }
                }
                return;
            }
            
            // Normal mode keyboard shortcuts
            if (!currentRequest) return;
            
            const num = parseInt(e.key);
            if (num >= 1 && num <= currentRequest.options.length) {
                selectAndSubmit(num - 1);
            } else if (e.key.toLowerCase() === 'y' && currentRequest.options.length === 1) {
                selectAndSubmit(0);
            } else if (e.key.toLowerCase() === 'n' || e.key.toLowerCase() === 'r') {
                submitRegenerate();
            }
        });
        
        // Keep alive
        setInterval(() => {
            if (ws?.readyState === WebSocket.OPEN) ws.send('ping');
        }, 30000);
        
        // ===== LIGHTBOX =====
        const lightbox = $('lightbox');
        const lightboxImg = $('lightboxImg');
        const lightboxCaption = $('lightboxCaption');
        const zoomLevelEl = $('zoomLevel');
        
        let lightboxImages = [];
        let lightboxIndex = 0;
        let currentZoom = 1;
        let isDragging = false;
        let dragStart = { x: 0, y: 0 };
        let imgOffset = { x: 0, y: 0 };
        
        function openLightbox(imgSrc, caption = '', images = null, index = 0) {
            if (images && images.length > 0) {
                lightboxImages = images;
                lightboxIndex = index;
            } else {
                lightboxImages = [{ src: imgSrc, caption: caption }];
                lightboxIndex = 0;
            }
            
            showLightboxImage();
            lightbox.classList.add('visible');
            document.body.style.overflow = 'hidden';
            updateNavButtons();
        }
        
        function showLightboxImage() {
            const img = lightboxImages[lightboxIndex];
            lightboxImg.src = img.src;
            lightboxCaption.textContent = img.caption || `Image ${lightboxIndex + 1} of ${lightboxImages.length}`;
            resetZoom();
        }
        
        function closeLightbox() {
            lightbox.classList.remove('visible');
            document.body.style.overflow = '';
            lightboxImages = [];
            resetZoom();
        }
        
        function closeLightboxOnBackdrop(e) {
            if (e.target === lightbox) {
                closeLightbox();
            }
        }
        
        function lightboxPrev() {
            if (lightboxIndex > 0) {
                lightboxIndex--;
                showLightboxImage();
                updateNavButtons();
            }
        }
        
        function lightboxNext() {
            if (lightboxIndex < lightboxImages.length - 1) {
                lightboxIndex++;
                showLightboxImage();
                updateNavButtons();
            }
        }
        
        function updateNavButtons() {
            const prevBtn = document.querySelector('.lightbox-nav.prev');
            const nextBtn = document.querySelector('.lightbox-nav.next');
            prevBtn.disabled = lightboxIndex === 0;
            nextBtn.disabled = lightboxIndex === lightboxImages.length - 1;
            prevBtn.style.display = lightboxImages.length <= 1 ? 'none' : 'flex';
            nextBtn.style.display = lightboxImages.length <= 1 ? 'none' : 'flex';
        }
        
        function zoomIn() {
            currentZoom = Math.min(currentZoom + 0.25, 5);
            applyZoom();
        }
        
        function zoomOut() {
            currentZoom = Math.max(currentZoom - 0.25, 0.25);
            applyZoom();
        }
        
        function resetZoom() {
            currentZoom = 1;
            imgOffset = { x: 0, y: 0 };
            applyZoom();
        }
        
        function toggleZoom() {
            if (currentZoom === 1) {
                currentZoom = 2;
            } else {
                currentZoom = 1;
                imgOffset = { x: 0, y: 0 };
            }
            applyZoom();
        }
        
        function applyZoom() {
            lightboxImg.style.transform = `scale(${currentZoom}) translate(${imgOffset.x}px, ${imgOffset.y}px)`;
            zoomLevelEl.textContent = `${Math.round(currentZoom * 100)}%`;
            lightboxImg.classList.toggle('zoomed', currentZoom > 1);
        }
        
        function startDrag(e) {
            if (currentZoom <= 1) return;
            isDragging = true;
            dragStart = { x: e.clientX - imgOffset.x * currentZoom, y: e.clientY - imgOffset.y * currentZoom };
            lightboxImg.classList.add('dragging');
            e.preventDefault();
        }
        
        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            imgOffset.x = (e.clientX - dragStart.x) / currentZoom;
            imgOffset.y = (e.clientY - dragStart.y) / currentZoom;
            applyZoom();
        });
        
        document.addEventListener('mouseup', () => {
            isDragging = false;
            lightboxImg.classList.remove('dragging');
        });
        
        // Keyboard controls
        document.addEventListener('keydown', (e) => {
            if (!lightbox.classList.contains('visible')) return;
            
            switch(e.key) {
                case 'Escape': closeLightbox(); break;
                case 'ArrowLeft': lightboxPrev(); break;
                case 'ArrowRight': lightboxNext(); break;
                case '+': case '=': zoomIn(); break;
                case '-': zoomOut(); break;
                case '0': resetZoom(); break;
            }
        });
        
        // Mouse wheel zoom
        lightbox.addEventListener('wheel', (e) => {
            if (!lightbox.classList.contains('visible')) return;
            e.preventDefault();
            if (e.deltaY < 0) {
                zoomIn();
            } else {
                zoomOut();
            }
        });
        
        // Helper to make images clickable for lightbox
        function setupImageLightbox(container) {
            const images = container.querySelectorAll('img');
            const imageData = Array.from(images).map((img, i) => ({
                src: img.src,
                caption: img.alt || img.closest('.history-image-card')?.querySelector('.history-image-label')?.textContent || `Image ${i + 1}`
            }));
            
            images.forEach((img, i) => {
                img.style.cursor = 'zoom-in';
                img.onclick = (e) => {
                    e.stopPropagation();
                    openLightbox(img.src, imageData[i].caption, imageData, i);
                };
            });
        }
        
        // Watch for new images and make them clickable
        const imageObserver = new MutationObserver((mutations) => {
            mutations.forEach(m => {
                m.addedNodes.forEach(node => {
                    if (node.nodeType === 1) {
                        if (node.matches?.('.history-images, .approval-images, .option-grid, .queue-options-grid')) {
                            setupImageLightbox(node);
                        }
                        node.querySelectorAll?.('.history-images, .approval-images, .option-grid, .queue-options-grid').forEach(setupImageLightbox);
                    }
                });
            });
        });
        imageObserver.observe(document.body, { childList: true, subtree: true });
        
        // Start
        connect();
    </script>
</body>
</html>'''


# --- Server Runner ---

class WebServer:
    """
    Runs the web server in a background thread.
    
    Usage:
        server = WebServer(port=8080)
        server.start(base_path=Path("."))
        
        # ... pipeline runs ...
        
        server.stop()
    """
    
    def __init__(self, port: int = 8080, host: str = "127.0.0.1"):
        self.port = port
        self.host = host
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
    
    def start(self, base_path: Path, open_browser: bool = True) -> None:
        """Start the server in a background thread."""
        set_base_path(base_path)
        
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",  # Reduce noise
        )
        self._server = uvicorn.Server(config)
        
        def run():
            # Run in its own event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._started.set()
            loop.run_until_complete(self._server.serve())
        
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        
        # Wait for server to start
        self._started.wait(timeout=5)
        
        # Small delay to ensure server is ready
        import time
        time.sleep(0.5)
        
        if open_browser:
            url = f"http://{self.host}:{self.port}"
            webbrowser.open(url)
    
    def stop(self) -> None:
        """Stop the server."""
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=2)
    
    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"
