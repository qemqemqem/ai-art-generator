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
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #ffffff;
            color: #1a1a1a;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1000px;
            margin: 0 auto;
            padding: 24px;
        }
        
        /* Header */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 0;
            border-bottom: 1px solid #e5e5e5;
            margin-bottom: 24px;
        }
        
        .logo {
            font-size: 18px;
            font-weight: 600;
            color: #1a1a1a;
        }
        
        .status-badge {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: #666;
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #22c55e;
        }
        
        .status-dot.waiting {
            background: #f59e0b;
            animation: pulse 2s infinite;
        }
        
        .status-dot.error {
            background: #ef4444;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        /* Main Layout */
        .main-layout {
            display: grid;
            grid-template-columns: 1fr 280px;
            gap: 32px;
        }
        
        @media (max-width: 768px) {
            .main-layout {
                grid-template-columns: 1fr;
            }
        }
        
        /* Progress Section */
        .progress-section {
            margin-bottom: 32px;
        }
        
        .progress-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 12px;
        }
        
        .progress-title {
            font-size: 16px;
            font-weight: 600;
            color: #1a1a1a;
        }
        
        .progress-percent {
            font-size: 14px;
            font-weight: 600;
            color: #3b82f6;
        }
        
        .pipeline-description {
            font-size: 13px;
            color: #666;
            margin-bottom: 16px;
        }
        
        .progress-bar {
            height: 6px;
            background: #e5e5e5;
            border-radius: 3px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: #3b82f6;
            border-radius: 3px;
            transition: width 0.3s ease;
        }
        
        .progress-stats {
            margin-top: 16px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
        }
        
        .progress-stat {
            text-align: center;
            padding: 12px 8px;
            background: #f9fafb;
            border-radius: 8px;
        }
        
        .progress-stat-value {
            font-size: 18px;
            font-weight: 600;
            color: #1a1a1a;
        }
        
        .progress-stat-label {
            font-size: 11px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        /* Current Stage Details */
        .stage-details {
            background: #f9fafb;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 32px;
        }
        
        .stage-details.hidden {
            display: none;
        }
        
        .stage-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
        }
        
        .stage-icon {
            width: 32px;
            height: 32px;
            background: #3b82f6;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 14px;
        }
        
        .stage-title {
            font-size: 15px;
            font-weight: 600;
        }
        
        .stage-type {
            font-size: 12px;
            color: #666;
            background: #e5e7eb;
            padding: 2px 8px;
            border-radius: 4px;
        }
        
        .stage-description {
            font-size: 14px;
            color: #374151;
            margin-bottom: 12px;
            line-height: 1.5;
        }
        
        .stage-prompt {
            background: white;
            border: 1px solid #e5e5e5;
            border-radius: 8px;
            padding: 12px;
            font-size: 13px;
            color: #4b5563;
            line-height: 1.5;
            max-height: 120px;
            overflow-y: auto;
        }
        
        .stage-prompt-label {
            font-size: 11px;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        
        .context-panel {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 12px;
        }
        
        @media (max-width: 600px) {
            .context-panel {
                grid-template-columns: 1fr;
            }
        }
        
        .context-row {
            background: white;
            border: 1px solid #e5e5e5;
            border-radius: 8px;
            padding: 12px;
        }
        
        .context-label {
            font-size: 10px;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        
        .context-values {
            font-size: 12px;
            color: #374151;
        }
        
        .context-item {
            display: flex;
            margin-bottom: 4px;
        }
        
        .context-item:last-child {
            margin-bottom: 0;
        }
        
        .context-key {
            font-weight: 500;
            min-width: 80px;
            color: #6b7280;
        }
        
        .context-value {
            color: #1a1a1a;
            word-break: break-word;
        }
        
        .message {
            margin-top: 12px;
            font-size: 13px;
            color: #666;
            font-style: italic;
        }
        
        /* Pipeline Overview */
        .pipeline-overview {
            background: #f9fafb;
            border-radius: 12px;
            padding: 16px;
        }
        
        .pipeline-overview-title {
            font-size: 12px;
            font-weight: 600;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 12px;
        }
        
        .pipeline-steps {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .pipeline-step {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 10px;
            background: white;
            border-radius: 6px;
            font-size: 12px;
            border: 1px solid transparent;
        }
        
        .pipeline-step.running {
            border-color: #3b82f6;
            background: #eff6ff;
        }
        
        .pipeline-step.complete {
            opacity: 0.6;
        }
        
        .step-indicator {
            width: 18px;
            height: 18px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            flex-shrink: 0;
        }
        
        .step-indicator.pending {
            background: #e5e7eb;
            color: #9ca3af;
        }
        
        .step-indicator.running {
            background: #3b82f6;
            color: white;
        }
        
        .step-indicator.complete {
            background: #22c55e;
            color: white;
        }
        
        .step-indicator.skipped {
            background: #9ca3af;
            color: white;
        }
        
        .step-indicator.failed {
            background: #ef4444;
            color: white;
        }
        
        .step-name {
            flex: 1;
            font-weight: 500;
            color: #374151;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .step-type-badge {
            font-size: 10px;
            color: #9ca3af;
            background: #f3f4f6;
            padding: 2px 6px;
            border-radius: 3px;
        }
        
        /* Approval Section */
        .approval-section {
            display: none;
        }
        
        .approval-section.visible {
            display: block;
        }
        
        .approval-header {
            margin-bottom: 20px;
        }
        
        .approval-title {
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        
        .approval-subtitle {
            font-size: 14px;
            color: #666;
        }
        
        /* Generation details in approval */
        .generation-details {
            background: #f9fafb;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 20px;
        }
        
        .generation-details-label {
            font-size: 11px;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        
        .generation-prompt-text {
            font-size: 13px;
            color: #4b5563;
            line-height: 1.5;
            white-space: pre-wrap;
            max-height: 100px;
            overflow-y: auto;
        }
        
        .options-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }
        
        .option-card {
            border: 2px solid #e5e5e5;
            border-radius: 12px;
            overflow: hidden;
            cursor: pointer;
            transition: all 0.15s ease;
            position: relative;
        }
        
        .option-card:hover {
            border-color: #3b82f6;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.15);
        }
        
        .option-card:active {
            transform: translateY(0);
        }
        
        .option-card.selected {
            border-color: #22c55e;
            background: #f0fdf4;
        }
        
        .option-image {
            width: 100%;
            aspect-ratio: 1;
            object-fit: cover;
            background: #f3f4f6;
        }
        
        .option-content {
            padding: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .option-label {
            font-size: 14px;
            font-weight: 500;
        }
        
        .option-text {
            padding: 16px;
            font-size: 14px;
            line-height: 1.6;
            max-height: 180px;
            overflow-y: auto;
            white-space: pre-wrap;
        }
        
        .option-number {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 24px;
            height: 24px;
            background: #e5e5e5;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .option-card:hover .option-number {
            background: #3b82f6;
            color: white;
        }
        
        .option-card.selected .option-number {
            background: #22c55e;
            color: white;
        }
        
        .click-hint {
            position: absolute;
            top: 8px;
            right: 8px;
            background: rgba(0,0,0,0.6);
            color: white;
            font-size: 11px;
            padding: 4px 8px;
            border-radius: 4px;
            opacity: 0;
            transition: opacity 0.15s;
        }
        
        .option-card:hover .click-hint {
            opacity: 1;
        }
        
        /* Actions */
        .actions {
            display: flex;
            gap: 12px;
            justify-content: flex-start;
            padding-top: 16px;
            border-top: 1px solid #e5e5e5;
        }
        
        .btn {
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s ease;
            border: none;
        }
        
        .btn-secondary {
            background: #f3f4f6;
            color: #374151;
        }
        
        .btn-secondary:hover {
            background: #e5e7eb;
        }
        
        .btn-danger {
            background: #fee2e2;
            color: #dc2626;
        }
        
        .btn-danger:hover {
            background: #fecaca;
        }
        
        /* Keyboard hints */
        .keyboard-hints {
            margin-top: 12px;
            font-size: 12px;
            color: #9ca3af;
        }
        
        kbd {
            display: inline-block;
            padding: 2px 6px;
            background: #f3f4f6;
            border: 1px solid #d1d5db;
            border-radius: 4px;
            font-family: monospace;
            font-size: 11px;
        }
        
        /* Complete Section */
        .complete-section {
            display: none;
            text-align: center;
            padding: 64px 0;
        }
        
        .complete-section.visible {
            display: block;
        }
        
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
            font-size: 32px;
        }
        
        .complete-title {
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        
        .complete-subtitle {
            font-size: 14px;
            color: #666;
            margin-bottom: 24px;
        }
        
        .results-summary {
            display: inline-grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 24px;
            padding: 24px;
            background: #f9fafb;
            border-radius: 12px;
            margin-bottom: 24px;
        }
        
        .result-item {
            text-align: center;
        }
        
        .result-value {
            font-size: 24px;
            font-weight: 600;
            color: #1a1a1a;
        }
        
        .result-label {
            font-size: 12px;
            color: #666;
        }
        
        /* Error display */
        .error-list {
            margin-top: 16px;
            padding: 16px;
            background: #fef2f2;
            border-radius: 8px;
            border: 1px solid #fecaca;
        }
        
        .error-item {
            font-size: 13px;
            color: #dc2626;
            margin-bottom: 4px;
        }
        
        .error-item:last-child {
            margin-bottom: 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">ArtGen Pipeline</div>
            <div class="status-badge">
                <div class="status-dot" id="statusDot"></div>
                <span id="statusText">Connecting...</span>
            </div>
        </header>
        
        <div class="main-layout">
            <div class="main-content">
                <!-- Progress Section -->
                <section class="progress-section" id="progressSection">
                    <div class="progress-header">
                        <span class="progress-title" id="pipelineName">Loading pipeline...</span>
                        <span class="progress-percent" id="progressPercent">0%</span>
                    </div>
                    <div class="pipeline-description" id="pipelineDescription"></div>
                    <div class="progress-bar">
                        <div class="progress-fill" id="progressFill" style="width: 0%"></div>
                    </div>
                    <div class="progress-stats">
                        <div class="progress-stat">
                            <div class="progress-stat-value" id="stepsProgress">0/0</div>
                            <div class="progress-stat-label">Steps</div>
                        </div>
                        <div class="progress-stat">
                            <div class="progress-stat-value" id="assetsProgress">0/0</div>
                            <div class="progress-stat-label">Assets</div>
                        </div>
                        <div class="progress-stat">
                            <div class="progress-stat-value" id="currentAsset">-</div>
                            <div class="progress-stat-label">Current</div>
                        </div>
                    </div>
                </section>
                
                <!-- Current Stage Details -->
                <section class="stage-details hidden" id="stageDetails">
                    <div class="stage-header">
                        <div class="stage-icon" id="stageIcon">▶</div>
                        <div>
                            <div class="stage-title" id="stageTitle">-</div>
                            <span class="stage-type" id="stageType">-</span>
                        </div>
                    </div>
                    <div class="stage-description" id="stageDescription">-</div>
                    
                    <!-- Asset & Context Info -->
                    <div class="context-panel" id="contextPanel" style="display: none;">
                        <div class="context-row" id="assetInfo" style="display: none;">
                            <div class="context-label">Current Asset</div>
                            <div class="context-values" id="assetValues"></div>
                        </div>
                        <div class="context-row" id="contextInfo" style="display: none;">
                            <div class="context-label">Pipeline Context</div>
                            <div class="context-values" id="contextValues"></div>
                        </div>
                    </div>
                    
                    <div id="stagePromptContainer" style="display: none;">
                        <div class="stage-prompt-label">Generation Prompt</div>
                        <div class="stage-prompt" id="stagePrompt"></div>
                    </div>
                    <div class="message" id="statusMessage"></div>
                </section>
                
                <div class="error-list" id="errorList" style="display: none;"></div>
                
                <!-- Approval Section -->
                <section class="approval-section" id="approvalSection">
                    <div class="approval-header">
                        <h2 class="approval-title" id="approvalTitle">Select Best Option</h2>
                        <p class="approval-subtitle" id="approvalSubtitle">Click on an option to select it</p>
                    </div>
                    
                    <div class="generation-details" id="generationDetails" style="display: none;">
                        <div class="generation-details-label">Prompt Used</div>
                        <div class="generation-prompt-text" id="generationPrompt"></div>
                    </div>
                    
                    <div class="options-grid" id="optionsGrid"></div>
                    
                    <div class="actions">
                        <button class="btn btn-secondary" id="regenerateBtn">Regenerate All</button>
                    </div>
                    
                    <div class="keyboard-hints">
                        <kbd>1</kbd>-<kbd>9</kbd> select option &nbsp;&bull;&nbsp;
                        <kbd>Y</kbd> approve &nbsp;&bull;&nbsp;
                        <kbd>N</kbd> reject &nbsp;&bull;&nbsp;
                        <kbd>R</kbd> regenerate
                    </div>
                </section>
                
                <!-- Complete Section -->
                <section class="complete-section" id="completeSection">
                    <div class="complete-icon">✓</div>
                    <h2 class="complete-title">Pipeline Complete</h2>
                    <p class="complete-subtitle" id="completeMessage">All assets have been processed.</p>
                    
                    <div class="results-summary" id="resultsSummary">
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
                    
                    <button class="btn btn-secondary" id="closeBtn">Close Window</button>
                </section>
            </div>
            
            <!-- Pipeline Overview Sidebar -->
            <aside class="pipeline-overview" id="pipelineOverview">
                <div class="pipeline-overview-title">Pipeline Steps</div>
                <div class="pipeline-steps" id="pipelineSteps">
                    <div style="color: #9ca3af; font-size: 12px;">Loading...</div>
                </div>
            </aside>
        </div>
    </div>
    
    <script>
        // State
        let ws = null;
        let selectedIndex = null;
        let currentRequest = null;
        let startTime = null;
        let pipelineStepsData = [];
        
        // Elements
        const statusDot = document.getElementById('statusDot');
        const statusText = document.getElementById('statusText');
        const pipelineName = document.getElementById('pipelineName');
        const pipelineDescription = document.getElementById('pipelineDescription');
        const progressPercent = document.getElementById('progressPercent');
        const progressFill = document.getElementById('progressFill');
        const stepsProgress = document.getElementById('stepsProgress');
        const assetsProgress = document.getElementById('assetsProgress');
        const currentAsset = document.getElementById('currentAsset');
        const statusMessage = document.getElementById('statusMessage');
        const errorList = document.getElementById('errorList');
        const stageDetails = document.getElementById('stageDetails');
        const stageIcon = document.getElementById('stageIcon');
        const stageTitle = document.getElementById('stageTitle');
        const stageType = document.getElementById('stageType');
        const stageDescription = document.getElementById('stageDescription');
        const stagePromptContainer = document.getElementById('stagePromptContainer');
        const stagePrompt = document.getElementById('stagePrompt');
        const approvalSection = document.getElementById('approvalSection');
        const approvalTitle = document.getElementById('approvalTitle');
        const approvalSubtitle = document.getElementById('approvalSubtitle');
        const generationDetails = document.getElementById('generationDetails');
        const generationPrompt = document.getElementById('generationPrompt');
        const optionsGrid = document.getElementById('optionsGrid');
        const regenerateBtn = document.getElementById('regenerateBtn');
        const completeSection = document.getElementById('completeSection');
        const totalAssets = document.getElementById('totalAssets');
        const totalSteps = document.getElementById('totalSteps');
        const duration = document.getElementById('duration');
        const closeBtn = document.getElementById('closeBtn');
        const pipelineSteps = document.getElementById('pipelineSteps');
        
        // Connect WebSocket
        function connect() {
            const wsUrl = `ws://${window.location.host}/ws`;
            ws = new WebSocket(wsUrl);
            
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
                statusText.textContent = 'Connection error';
            };
            
            ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    // Ignore pong messages (keep-alive response)
                    if (msg.type === 'pong') return;
                    handleMessage(msg);
                } catch (e) {
                    // Log only non-pong parse errors
                    if (event.data !== 'pong') {
                        console.error('Failed to parse message:', e, event.data);
                    }
                }
            };
        }
        
        // Handle incoming messages
        function handleMessage(msg) {
            switch (msg.type) {
                case 'connected':
                    if (msg.data.progress) updateProgress(msg.data.progress);
                    if (msg.data.pending && msg.data.pending.length > 0) {
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
        
        // Update progress display
        function updateProgress(data) {
            if (!startTime && data.started_at) {
                startTime = new Date(data.started_at);
            }
            
            pipelineName.textContent = data.pipeline_name || 'Pipeline';
            pipelineDescription.textContent = data.pipeline_description || '';
            progressPercent.textContent = `${data.percent || 0}%`;
            progressFill.style.width = `${data.percent || 0}%`;
            stepsProgress.textContent = `${data.completed_steps || 0}/${data.total_steps || 0}`;
            assetsProgress.textContent = `${data.completed_assets || 0}/${data.total_assets || 0}`;
            currentAsset.textContent = data.current_asset || '-';
            statusMessage.textContent = data.message || '';
            
            // Update stage details
            if (data.current_step && data.phase === 'running') {
                stageDetails.classList.remove('hidden');
                stageTitle.textContent = data.current_step;
                stageType.textContent = data.current_step_type || '';
                stageDescription.textContent = data.current_step_description || 'Processing...';
                
                if (data.current_step_prompt) {
                    stagePromptContainer.style.display = 'block';
                    stagePrompt.textContent = data.current_step_prompt;
                } else {
                    stagePromptContainer.style.display = 'none';
                }
                
                // Update icon based on step type
                const typeIcons = {
                    'generate_image': '🎨',
                    'generate_sprite': '🎮',
                    'generate_text': '📝',
                    'research': '🔍',
                    'assess': '🔬',
                    'user_select': '👆',
                    'user_approve': '✅',
                };
                stageIcon.textContent = typeIcons[data.current_step_type] || '▶';
                
                // Update asset and context info panels
                updateContextPanel(data);
            }
            
            // Update status badge
            if (data.phase === 'waiting') {
                statusDot.className = 'status-dot waiting';
                statusText.textContent = 'Waiting for input';
            } else if (data.phase === 'running') {
                statusDot.className = 'status-dot';
                statusText.textContent = 'Running';
                // Hide approval section if it was showing (selection was made)
                if (approvalSection.classList.contains('visible')) {
                    approvalSection.classList.remove('visible');
                    currentRequest = null;
                    selectedIndex = null;
                }
            } else if (data.phase === 'complete') {
                showComplete(data);
            } else if (data.phase === 'failed') {
                statusDot.className = 'status-dot error';
                statusText.textContent = 'Failed';
            }
            
            // Update pipeline steps sidebar
            if (data.pipeline_steps && data.pipeline_steps.length > 0) {
                pipelineStepsData = data.pipeline_steps;
                renderPipelineSteps();
            }
            
            // Show errors
            if (data.errors && data.errors.length > 0) {
                errorList.style.display = 'block';
                errorList.innerHTML = data.errors
                    .map(e => `<div class="error-item">• ${e}</div>`)
                    .join('');
            } else {
                errorList.style.display = 'none';
            }
        }
        
        // Render context values as HTML
        function renderContextValues(obj) {
            if (!obj || Object.keys(obj).length === 0) return '';
            return Object.entries(obj).map(([key, value]) => {
                let displayValue = value;
                if (typeof value === 'object') {
                    displayValue = JSON.stringify(value);
                } else if (typeof value === 'string' && value.length > 100) {
                    displayValue = value.substring(0, 97) + '...';
                }
                return `<div class="context-item"><span class="context-key">${key}:</span> <span class="context-value">${displayValue}</span></div>`;
            }).join('');
        }
        
        // Update asset and context info panels
        function updateContextPanel(data) {
            const contextPanel = document.getElementById('contextPanel');
            const assetInfo = document.getElementById('assetInfo');
            const assetValues = document.getElementById('assetValues');
            const contextInfo = document.getElementById('contextInfo');
            const contextValues = document.getElementById('contextValues');
            
            let hasContent = false;
            
            // Show asset data if available
            if (data.current_asset_data && Object.keys(data.current_asset_data).length > 0) {
                assetInfo.style.display = 'block';
                assetValues.innerHTML = renderContextValues(data.current_asset_data);
                hasContent = true;
            } else {
                assetInfo.style.display = 'none';
            }
            
            // Show context data if available
            if (data.context_data && Object.keys(data.context_data).length > 0) {
                contextInfo.style.display = 'block';
                contextValues.innerHTML = renderContextValues(data.context_data);
                hasContent = true;
            } else {
                contextInfo.style.display = 'none';
            }
            
            contextPanel.style.display = hasContent ? 'grid' : 'none';
        }
        
        // Render pipeline steps in sidebar
        function renderPipelineSteps() {
            const statusIcons = {
                'pending': '○',
                'running': '●',
                'complete': '✓',
                'skipped': '–',
                'failed': '✕',
            };
            
            pipelineSteps.innerHTML = pipelineStepsData.map(step => `
                <div class="pipeline-step ${step.status}">
                    <div class="step-indicator ${step.status}">${statusIcons[step.status] || '○'}</div>
                    <span class="step-name" title="${step.description || step.id}">${step.id}</span>
                    ${step.for_each ? '<span class="step-type-badge">per-asset</span>' : ''}
                </div>
            `).join('');
        }
        
        // Show approval UI
        function showApproval(request) {
            currentRequest = request;
            selectedIndex = null;
            
            approvalSection.classList.add('visible');
            
            const isSelect = request.type === 'select_one';
            const isApprove = request.type === 'approve';
            
            approvalTitle.textContent = isSelect 
                ? `Select best option for "${request.asset_name}"`
                : `Approve result for "${request.asset_name}"?`;
            
            approvalSubtitle.textContent = isSelect
                ? 'Click on an option to select it'
                : 'Click the image to approve, or use the buttons below';
            
            // Show generation prompt if available
            if (request.generation_prompt) {
                generationDetails.style.display = 'block';
                generationPrompt.textContent = request.generation_prompt;
            } else {
                generationDetails.style.display = 'none';
            }
            
            // Render options
            optionsGrid.innerHTML = '';
            request.options.forEach((opt, i) => {
                const card = document.createElement('div');
                card.className = 'option-card';
                card.dataset.index = i;
                
                if (opt.path || opt.image_path) {
                    const imgPath = opt.path || opt.image_path;
                    const hintText = isApprove ? 'Click to approve' : 'Click to select';
                    card.innerHTML = `
                        <div class="click-hint">${hintText}</div>
                        <img class="option-image" src="/files/${imgPath}" alt="Option ${i + 1}">
                        <div class="option-content">
                            <span class="option-number">${i + 1}</span>
                            <span class="option-label">${isApprove ? 'Generated Result' : `Option ${i + 1}`}</span>
                        </div>
                    `;
                } else if (opt.text || opt.content) {
                    card.innerHTML = `
                        <div class="click-hint">Click to ${isApprove ? 'approve' : 'select'}</div>
                        <div class="option-text">${opt.text || opt.content}</div>
                        <div class="option-content">
                            <span class="option-number">${i + 1}</span>
                            <span class="option-label">${isApprove ? 'Generated Result' : `Option ${i + 1}`}</span>
                        </div>
                    `;
                }
                
                // Direct selection on click (no confirm needed)
                card.onclick = () => {
                    selectAndSubmit(i);
                };
                optionsGrid.appendChild(card);
            });
            
            // For approve type with single option, add reject button
            if (isApprove) {
                regenerateBtn.textContent = 'Reject & Regenerate';
            } else {
                regenerateBtn.textContent = 'Regenerate All';
            }
        }
        
        // Select and immediately submit
        async function selectAndSubmit(index) {
            if (!currentRequest) return;
            
            // Visual feedback
            document.querySelectorAll('.option-card').forEach((card, i) => {
                card.classList.toggle('selected', i === index);
            });
            
            // Short delay for visual feedback
            await new Promise(resolve => setTimeout(resolve, 150));
            
            try {
                const response = await fetch('/api/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        request_id: currentRequest.id,
                        approved: true,
                        selected_index: index,
                        regenerate: false,
                    }),
                });
                
                if (response.ok) {
                    approvalSection.classList.remove('visible');
                    currentRequest = null;
                    selectedIndex = null;
                }
            } catch (e) {
                console.error('Failed to submit:', e);
            }
        }
        
        // Submit regeneration request
        async function submitRegenerate() {
            if (!currentRequest) return;
            
            try {
                const response = await fetch('/api/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        request_id: currentRequest.id,
                        approved: false,
                        selected_index: null,
                        regenerate: true,
                    }),
                });
                
                if (response.ok) {
                    approvalSection.classList.remove('visible');
                    currentRequest = null;
                    selectedIndex = null;
                }
            } catch (e) {
                console.error('Failed to submit:', e);
            }
        }
        
        // Show complete state
        function showComplete(data) {
            approvalSection.classList.remove('visible');
            stageDetails.classList.add('hidden');
            completeSection.classList.add('visible');
            
            totalAssets.textContent = data.total_assets || 0;
            totalSteps.textContent = data.total_steps || 0;
            
            if (startTime) {
                const elapsed = Math.floor((Date.now() - startTime.getTime()) / 1000);
                duration.textContent = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;
            }
        }
        
        // Close and shutdown
        async function closeAndShutdown() {
            try {
                await fetch('/api/shutdown', { method: 'POST' });
            } catch (e) {
                // Server may have already closed
            }
            window.close();
        }
        
        // Event listeners
        regenerateBtn.onclick = submitRegenerate;
        closeBtn.onclick = closeAndShutdown;
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (!currentRequest) return;
            
            const num = parseInt(e.key);
            if (num >= 1 && num <= currentRequest.options.length) {
                selectAndSubmit(num - 1);
            } else if (e.key.toLowerCase() === 'y' && currentRequest.options.length === 1) {
                // Y for approve (single option)
                selectAndSubmit(0);
            } else if (e.key.toLowerCase() === 'n' || e.key.toLowerCase() === 'r') {
                // N or R for reject/regenerate
                submitRegenerate();
            }
        });
        
        // Ping to keep connection alive
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send('ping');
            }
        }, 30000);
        
        // Start connection
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
