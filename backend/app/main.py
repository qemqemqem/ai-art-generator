"""FastAPI application for AI Art Generator.

Run this from within your project directory. The current working directory
is treated as the project root.
"""

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import get_config
from app.models import (
    Asset,
    AssetStatus,
    GenerateRequest,
    ApprovalRequest,
    InputItem,
    ProjectConfig,
    StyleConfig,
    PipelineStep,
)
from app.queue_manager import (
    get_queue_manager,
    ApprovalDecision,
    ApprovalItem,
    QueueStatus,
    GeneratedOption,
)
from parsers import parse_input_string, InputFormat
from pipeline import PipelineOrchestrator, Project
from providers import get_provider_registry

app = FastAPI(
    title="AI Art Generator",
    description="Batch AI art generation with interactive approval workflow",
    version="0.1.0",
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global project instance (loaded on startup)
_project: Optional[Project] = None


async def get_project() -> Project:
    """Get the current project."""
    global _project
    if _project is None:
        if Project.exists():
            _project = await Project.load()
        else:
            # Auto-initialize if no project exists
            _project = await Project.init()
    return _project


# --- Health & Info ---

@app.get("/")
async def root():
    """Root endpoint."""
    project = await get_project()
    return {
        "name": "AI Art Generator",
        "version": "0.1.0",
        "status": "running",
        "project": project.config.name,
        "project_path": str(project.path),
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/providers")
async def list_providers():
    """List available AI providers."""
    registry = get_provider_registry()
    return {
        "image": registry.list_image_providers(),
        "text": registry.list_text_providers(),
        "research": registry.list_research_providers(),
    }


# --- Project Info ---

@app.get("/project")
async def get_project_info():
    """Get current project details."""
    project = await get_project()
    return {
        "name": project.config.name,
        "path": str(project.path),
        "config": project.config.model_dump(),
        "asset_count": len(project._assets),
    }


@app.put("/project/config")
async def update_project_config(config: ProjectConfig):
    """Update project configuration (full replace)."""
    project = await get_project()
    project._config = config
    await project.save_config()
    return {"config": project.config.model_dump()}


class PartialConfigUpdate(BaseModel):
    """Partial configuration update."""
    name: Optional[str] = None
    description: Optional[str] = None
    style: Optional[StyleConfig] = None
    pipeline: Optional[list[PipelineStep]] = None
    default_image_provider: Optional[str] = None
    default_text_provider: Optional[str] = None
    settings: Optional[dict] = None


@app.patch("/project/config")
async def patch_project_config(updates: PartialConfigUpdate):
    """Update project configuration (partial update)."""
    project = await get_project()
    
    # Apply updates to existing config
    if updates.name is not None:
        project._config.name = updates.name
    if updates.description is not None:
        project._config.description = updates.description
    if updates.style is not None:
        project._config.style = updates.style
    if updates.pipeline is not None:
        project._config.pipeline = updates.pipeline
    if updates.default_image_provider is not None:
        project._config.default_image_provider = updates.default_image_provider
    if updates.default_text_provider is not None:
        project._config.default_text_provider = updates.default_text_provider
    if updates.settings is not None:
        project._config.settings = updates.settings
    
    await project.save_config()
    return {"config": project.config.model_dump()}


@app.post("/project/init")
async def init_project(config: Optional[ProjectConfig] = None):
    """Initialize a new project in the current directory."""
    global _project
    if Project.exists():
        raise HTTPException(status_code=400, detail="Project already exists in this directory")
    
    _project = await Project.init(config=config)
    return {
        "name": _project.config.name,
        "path": str(_project.path),
        "config": _project.config.model_dump(),
    }


# --- Asset Management ---

@app.get("/assets")
async def list_assets(status: Optional[AssetStatus] = None):
    """List assets in the project."""
    project = await get_project()
    
    assets = list(project._assets.values())
    if status:
        assets = [a for a in assets if a.status == status]
    
    return {"assets": [a.model_dump() for a in assets]}


@app.post("/assets")
async def add_assets(
    items: list[InputItem],
    background_tasks: BackgroundTasks,
    auto_start: bool = False,
):
    """Add assets from a list of input items."""
    project = await get_project()
    
    created_assets = []
    for item in items:
        asset = await project.create_asset(item)
        created_assets.append(asset)
    
    if auto_start:
        background_tasks.add_task(
            _process_assets_background,
            project,
            [a.id for a in created_assets],
        )
    
    return {"assets": [a.model_dump() for a in created_assets]}


class UploadInputRequest(BaseModel):
    """Request for uploading input content."""
    content: str
    format: InputFormat = InputFormat.TEXT


@app.post("/assets/upload")
async def upload_input(
    request: UploadInputRequest,
    background_tasks: BackgroundTasks,
    auto_start: bool = False,
):
    """Upload input content as a string."""
    project = await get_project()
    
    items = parse_input_string(request.content, request.format)
    
    created_assets = []
    for item in items:
        asset = await project.create_asset(item)
        created_assets.append(asset)
    
    if auto_start:
        background_tasks.add_task(
            _process_assets_background,
            project,
            [a.id for a in created_assets],
        )
    
    return {"assets": [a.model_dump() for a in created_assets]}


@app.get("/assets/{asset_id}")
async def get_asset(asset_id: str):
    """Get a specific asset."""
    project = await get_project()
    
    asset = project.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")
    
    return asset.model_dump()


# --- Processing ---

@app.post("/process")
async def process_all(
    background_tasks: BackgroundTasks,
    auto_approve: bool = False,
):
    """Start processing all pending assets."""
    project = await get_project()
    
    pending = project.get_pending_assets()
    
    if not pending:
        return {"message": "No pending assets to process"}
    
    background_tasks.add_task(
        _process_assets_background,
        project,
        [a.id for a in pending],
        auto_approve,
    )
    
    return {
        "message": f"Processing started for {len(pending)} assets",
        "asset_ids": [a.id for a in pending],
    }


@app.post("/assets/{asset_id}/process")
async def process_asset(
    asset_id: str,
    background_tasks: BackgroundTasks,
    auto_approve: bool = False,
):
    """Process a specific asset."""
    project = await get_project()
    
    asset = project.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")
    
    background_tasks.add_task(
        _process_assets_background,
        project,
        [asset_id],
        auto_approve,
    )
    
    return {"message": f"Processing started for asset {asset_id}"}


async def _process_assets_background(
    project: Project,
    asset_ids: list[str],
    auto_approve: bool = False,
):
    """Background task to process assets."""
    orchestrator = PipelineOrchestrator(project)
    
    for asset_id in asset_ids:
        asset = project.get_asset(asset_id)
        if asset:
            await orchestrator.process_asset(asset, auto_approve)


# --- Approval Queue (Legacy) ---

@app.get("/queue")
async def get_approval_queue():
    """Get the approval queue (legacy endpoint)."""
    project = await get_project()
    
    queue = project.get_queue()
    
    # Find step configs for each queue item
    items = []
    for asset, step_id, result in queue:
        step_config = None
        for step in project.config.pipeline:
            if step.id == step_id:
                step_config = step
                break
        
        items.append({
            "asset": asset.model_dump(),
            "step_id": step_id,
            "step_result": result.model_dump(),
            "step_config": step_config.model_dump() if step_config else None,
        })
    
    return {"queue": items}


# --- Interactive Mode Queue ---

@app.get("/interactive/status")
async def get_interactive_status():
    """Get interactive mode queue status."""
    queue_manager = get_queue_manager()
    return queue_manager.get_status().model_dump()


@app.get("/interactive/next")
async def get_next_approval():
    """Get the next item awaiting approval."""
    queue_manager = get_queue_manager()
    item = queue_manager.get_next_approval()
    
    if item is None:
        return {"item": None, "message": "No items awaiting approval"}
    
    return {"item": item.model_dump()}


@app.get("/interactive/approvals")
async def get_all_approvals():
    """Get all items awaiting approval."""
    queue_manager = get_queue_manager()
    items = queue_manager.get_all_approvals()
    return {"items": [i.model_dump() for i in items]}


@app.get("/interactive/generating")
async def get_generating_items():
    """Get items currently being generated."""
    queue_manager = get_queue_manager()
    items = queue_manager.get_generating_items()
    return {"items": [i.model_dump() for i in items]}


@app.post("/interactive/approve")
async def approve_interactive(decision: ApprovalDecision, background_tasks: BackgroundTasks):
    """Submit an approval decision."""
    queue_manager = get_queue_manager()
    result = await queue_manager.submit_decision(decision)
    
    # If approved, continue processing the asset
    if result.get("status") == "approved":
        project = await get_project()
        asset_id = result.get("asset_id")
        if asset_id:
            asset = project.get_asset(asset_id)
            if asset:
                background_tasks.add_task(
                    _continue_processing,
                    project,
                    asset_id,
                    result.get("step_id"),
                    result.get("selected"),
                )
    
    return result


@app.post("/interactive/skip/{item_id}")
async def skip_approval(item_id: str):
    """Skip an approval item."""
    queue_manager = get_queue_manager()
    return queue_manager.skip_item(item_id)


@app.post("/interactive/regenerate/{item_id}")
async def regenerate_item(item_id: str, background_tasks: BackgroundTasks):
    """Request regeneration for an item."""
    queue_manager = get_queue_manager()
    decision = ApprovalDecision(
        item_id=item_id,
        approved=False,
        regenerate=True,
    )
    result = await queue_manager.submit_decision(decision)
    
    # TODO: Trigger regeneration in background worker
    
    return result


# --- Generation Control ---

@app.post("/interactive/start")
async def start_interactive(background_tasks: BackgroundTasks):
    """Start interactive generation."""
    queue_manager = get_queue_manager()
    project = await get_project()
    
    # Clear any stale state
    queue_manager.clear()
    
    # Load ALL assets (not just pending) to track total
    all_assets = list(project._assets.values())
    queue_manager.add_assets(all_assets)
    
    # Rebuild approval queue from any assets awaiting approval
    awaiting = project.get_awaiting_approval()
    for asset in awaiting:
        # Find the step that needs approval
        for step_id, result in asset.results.items():
            if result.status == AssetStatus.AWAITING_APPROVAL and not result.approved:
                # Find step config
                step_config = None
                for step in project.config.pipeline:
                    if step.id == step_id:
                        step_config = step
                        break
                
                if step_config and result.variations:
                    # Rebuild approval item
                    options = []
                    for v in result.variations:
                        if v.type in ("image", "sprite"):
                            options.append(GeneratedOption(
                                type="image",
                                image_path=v.path,
                                prompt_used=v.metadata.get("prompt", ""),
                            ))
                        else:
                            options.append(GeneratedOption(
                                type="text",
                                text_content=v.content,
                                prompt_used=v.metadata.get("prompt", ""),
                            ))
                    
                    from app.queue_manager import ApprovalItem, ApprovalType
                    approval_item = ApprovalItem(
                        asset_id=asset.id,
                        asset_description=asset.input_description,
                        step_id=step_id,
                        step_name=step_config.type.value if hasattr(step_config.type, 'value') else str(step_config.type),
                        step_index=project.config.pipeline.index(step_config),
                        total_steps=len(project.config.pipeline),
                        approval_type=ApprovalType.CHOOSE_ONE if len(result.variations) > 1 else ApprovalType.ACCEPT_REJECT,
                        options=options,
                        context={"description": asset.input_description},
                    )
                    queue_manager.add_approval_item(approval_item)
    
    # Also queue pending assets
    pending = project.get_pending_assets()
    for asset in pending:
        if asset.id not in queue_manager._pending_asset_ids:
            queue_manager._pending_asset_ids.append(asset.id)
    
    queue_manager.start()
    
    # Start background generation
    background_tasks.add_task(_run_interactive_generation, project)
    
    return {
        "status": "started",
        "assets_queued": len(pending),
        "approvals_restored": len(awaiting),
    }


@app.post("/interactive/pause")
async def pause_interactive():
    """Pause interactive generation."""
    queue_manager = get_queue_manager()
    queue_manager.pause()
    return {"status": "paused"}


@app.post("/interactive/resume")
async def resume_interactive(background_tasks: BackgroundTasks):
    """Resume interactive generation."""
    queue_manager = get_queue_manager()
    project = await get_project()
    
    queue_manager.resume()
    
    # Restart background generation
    background_tasks.add_task(_run_interactive_generation, project)
    
    return {"status": "resumed"}


@app.post("/interactive/stop")
async def stop_interactive():
    """Stop interactive generation."""
    queue_manager = get_queue_manager()
    queue_manager.stop()
    return {"status": "stopped"}


async def _continue_processing(
    project: Project,
    asset_id: str,
    completed_step_id: str,
    selected_option: Optional[dict],
):
    """Continue processing an asset after approval."""
    asset = project.get_asset(asset_id)
    if not asset:
        return
    
    # Update asset with selected option
    if selected_option and completed_step_id in asset.results:
        result = asset.results[completed_step_id]
        result.approved = True
        result.status = AssetStatus.APPROVED
        await project.save_asset(asset)
    
    # TODO: Continue to next step via interactive worker


async def _run_interactive_generation(project: Project):
    """Background task for interactive generation.
    
    This is the main generation loop that:
    1. Picks pending assets/steps
    2. Generates content
    3. Adds to approval queue
    4. Waits for approval before continuing
    """
    from app.worker import InteractiveWorker
    
    queue_manager = get_queue_manager()
    worker = InteractiveWorker(project, queue_manager)
    
    await worker.run()


@app.post("/approve")
async def approve_step(request: ApprovalRequest, background_tasks: BackgroundTasks):
    """Approve or reject a step result."""
    project = await get_project()
    
    asset = project.get_asset(request.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset not found: {request.asset_id}")
    
    orchestrator = PipelineOrchestrator(project)
    
    if request.approved:
        if request.selected_index is None:
            raise HTTPException(status_code=400, detail="selected_index required for approval")
        
        background_tasks.add_task(
            orchestrator.approve_step,
            asset,
            request.step_id,
            request.selected_index,
        )
        
        return {"message": "Approved", "asset_id": asset.id, "step_id": request.step_id}
    else:
        if request.regenerate:
            background_tasks.add_task(
                orchestrator.reject_step,
                asset,
                request.step_id,
                request.modified_prompt,
            )
            return {"message": "Rejected and regenerating", "asset_id": asset.id}
        else:
            result = asset.results.get(request.step_id)
            if result:
                result.status = AssetStatus.REJECTED
                asset.status = AssetStatus.FAILED
                await project.save_asset(asset)
            return {"message": "Rejected", "asset_id": asset.id}


# --- Quick Generation (standalone, no project) ---

@app.post("/generate")
async def quick_generate(request: GenerateRequest):
    """Quick generation without project context."""
    registry = get_provider_registry()
    provider = registry.get_image_provider(request.provider.value)
    
    images = await provider.generate(
        prompt=request.prompt,
        style=request.style,
        variations=request.variations,
    )
    
    import base64
    from io import BytesIO
    
    results = []
    for i, img in enumerate(images):
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode()
        results.append({
            "index": i,
            "width": img.width,
            "height": img.height,
            "data": f"data:image/png;base64,{b64}",
        })
    
    return {"images": results}


# --- Static Files (serving generated images) ---

@app.get("/files/{file_path:path}")
async def serve_file(file_path: str):
    """Serve a file from the project."""
    project = await get_project()
    
    full_path = project.path / file_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    
    return FileResponse(full_path)


# --- WebSocket ---

from app.websocket import get_connection_manager, setup_queue_callbacks

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    manager = get_connection_manager()
    await manager.connect(websocket)
    
    try:
        # Send initial status
        queue_manager = get_queue_manager()
        try:
            await manager.send_to(websocket, {
                "type": "connected",
                "status": queue_manager.get_status().model_dump(),
            })
        except Exception:
            # Client disconnected before we could send
            return
        
        # Keep connection alive and handle client messages
        while True:
            try:
                data = await websocket.receive_text()
                # Handle ping/pong
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
            except Exception:
                break
    finally:
        await manager.disconnect(websocket)


# --- Startup ---

@app.on_event("startup")
async def startup():
    """Initialize on startup."""
    project = await get_project()
    config = get_config()
    
    # Set up WebSocket callbacks
    setup_queue_callbacks()
    
    print(f"AI Art Generator started")
    print(f"  Project: {project.config.name}")
    print(f"  Path: {project.path}")
    print(f"  Assets: {len(project._assets)}")
    if config.env_file:
        print(f"  Env file: {config.env_file}")


@app.get("/config/env")
async def get_env_info():
    """Get info about loaded environment."""
    config = get_config()
    return {
        "env_file": config.env_file,
        "has_google_api_key": bool(config.providers.google_api_key),
        "has_openai_api_key": bool(config.providers.openai_api_key),
        "has_anthropic_api_key": bool(config.providers.anthropic_api_key),
        "has_tavily_api_key": bool(config.providers.tavily_api_key),
    }


if __name__ == "__main__":
    import argparse
    import uvicorn
    from app.config import reload_config
    
    parser = argparse.ArgumentParser(description="AI Art Generator Server")
    parser.add_argument(
        "--env", "-e",
        help="Path to .env file (can also set ARTGEN_ENV_FILE)",
        default=None,
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8000,
        help="Port to run on (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    
    args = parser.parse_args()
    
    # Reload config with explicit env path if provided
    if args.env:
        reload_config(args.env)
    
    config = get_config()
    uvicorn.run(app, host=args.host, port=args.port)
