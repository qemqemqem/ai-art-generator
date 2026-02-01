"""
Pipeline Executor.

Main execution engine that orchestrates:
  - Loading and validating pipeline specs
  - Loading assets from various sources
  - Executing steps in dependency order
  - Parallel execution within tiers and for assets
  - Managing caching and checkpoints
  - CLI-blocking human interactions
  - Retry logic and rate limiting
"""

import asyncio
import json
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from .asset_loader import load_assets, load_asset_collections
from .cache import CacheManager, should_skip_step
from .context import build_rich_context, get_asset_aware_step_outputs
from .executors import ExecutorContext, StepExecutor, StepResult, get_executor
from .expressions import evaluate_condition
from .retry import API_RETRY_CONFIG, retry_async
from .spec_parser import PipelineSpec, StepSpec, StepType, get_execution_order, load_pipeline
from .templates import substitute_all

# Import all executors to register them
from .executors import assess, image, text, user

console = Console()

# Default parallelism settings
DEFAULT_ASSET_PARALLELISM = 3  # Max concurrent assets
DEFAULT_TIER_PARALLELISM = 4   # Max concurrent steps in same tier


@contextmanager
def pause_progress(progress: Progress):
    """
    Context manager to pause Rich Progress for user input.
    
    Rich's Progress uses Live display which conflicts with stdin.
    This pauses the display, clears progress lines, allows input,
    then restarts the display.
    """
    # Stop the live display
    progress.stop()
    
    # Clear the progress lines from terminal
    # Move cursor up and clear each task line
    UP = "\x1b[1A"
    CLEAR = "\x1b[2K"
    for _ in progress.tasks:
        print(UP + CLEAR + UP, end="")
    
    try:
        yield
    finally:
        # Restart the live display
        progress.start()


@dataclass
class ExecutionResult:
    """Result of a full pipeline execution."""
    success: bool
    assets_processed: int
    steps_completed: int
    steps_skipped: int
    duration_ms: int
    errors: list[str]
    outputs_collected: dict[str, list[str]] | None = None  # asset_id -> list of output paths


class PipelineExecutor:
    """
    Executes pipeline specifications.
    
    Usage:
        executor = PipelineExecutor(pipeline_path)
        result = await executor.run()
    """
    
    def __init__(
        self,
        pipeline_path: Path | str,
        input_override: Path | str | None = None,
        auto_approve: bool = False,
        verbose: bool = False,
        asset_parallelism: int = DEFAULT_ASSET_PARALLELISM,
        tier_parallelism: int = DEFAULT_TIER_PARALLELISM,
        web_bridge: Any = None,
    ):
        """
        Initialize the executor.
        
        Args:
            pipeline_path: Path to pipeline YAML file
            input_override: Optional override for asset input file
            auto_approve: Skip human approval steps
            verbose: Show detailed output
            asset_parallelism: Max concurrent assets per step (default 3)
            tier_parallelism: Max concurrent steps in same tier (default 4)
            web_bridge: Optional WebApprovalBridge for web mode progress/approvals
        """
        self.pipeline_path = Path(pipeline_path)
        self.input_override = Path(input_override) if input_override else None
        self.auto_approve = auto_approve
        self.verbose = verbose
        self.asset_parallelism = asset_parallelism
        self.tier_parallelism = tier_parallelism
        self.web_bridge = web_bridge
        
        # Will be set during run()
        self.spec: PipelineSpec | None = None
        self.assets: list[dict[str, Any]] = []  # Legacy: default asset list
        self.asset_collections: dict[str, list[dict[str, Any]]] = {}  # Named collections
        self.cache: CacheManager | None = None
        self.providers: Any = None
        
        # Execution state
        self.context: dict[str, Any] = {}
        self.step_outputs: dict[str, Any] = {}
    
    def _update_web_progress(self, **kwargs) -> None:
        """Update web bridge progress if in web mode."""
        if self.web_bridge:
            self.web_bridge.update_progress(**kwargs)
    
    def _update_asset_status(self, asset_id: str, status: str) -> None:
        """Update the status of a specific asset in web progress."""
        if self.web_bridge:
            progress = self.web_bridge.get_progress()
            for asset_info in progress.assets:
                if asset_info.id == asset_id:
                    asset_info.status = status
                    break
            # Broadcast the updated progress
            self._update_web_progress()
    
    def _update_asset_data(self, asset_id: str, field_name: str, value: Any) -> None:
        """Update a specific field in an asset's data dictionary."""
        # Update in asset_collections
        for collection_name, items in self.asset_collections.items():
            for asset in items:
                if asset.get("id") == asset_id:
                    asset[field_name] = value
                    break
        
        # Update in web bridge
        if self.web_bridge:
            progress = self.web_bridge.get_progress()
            for asset_info in progress.assets:
                if asset_info.id == asset_id:
                    asset_info.data[field_name] = value
                    break
            # Broadcast the updated progress
            self._update_web_progress()
    
    def _get_step_providers(self, step: StepSpec) -> tuple[str, str, str | None, str | None]:
        """
        Get the resolved provider names for a step.
        
        Resolves from:
        1. Step-level `provider` override
        2. Pipeline-level `providers` defaults
        
        Returns:
            (text_provider, image_provider, text_model, image_model)
        """
        # Pipeline defaults
        text_provider = self.spec.providers.text
        image_provider = self.spec.providers.image
        text_model = self.spec.providers.text_model
        image_model = self.spec.providers.image_model
        
        # Step-level override
        if step.provider:
            # Determine if this is a text or image step and override accordingly
            if step.type.value in ("generate_text", "generate_name", "generate_prompt", "research"):
                text_provider = step.provider
            elif step.type.value in ("generate_image", "generate_sprite"):
                image_provider = step.provider
            else:
                # For other types, override both (user can specify)
                text_provider = step.provider
                image_provider = step.provider
        
        return text_provider, image_provider, text_model, image_model
    
    def _get_step_assets(self, step: StepSpec) -> list[dict[str, Any]]:
        """
        Get the assets for a step based on its for_each value.
        
        Args:
            step: The step to get assets for
            
        Returns:
            List of asset dictionaries. Empty if step has no for_each.
        """
        if not step.for_each:
            return []
        
        # Handle legacy "asset" value
        if step.for_each == "asset":
            # Return the first non-empty collection (backward compatibility)
            for items in self.asset_collections.values():
                if items:
                    return items
            return self.assets  # Fallback
        
        # Handle legacy "item" value (same as "asset")
        if step.for_each == "item":
            for items in self.asset_collections.values():
                if items:
                    return items
            return self.assets
        
        # Named collection
        if step.for_each in self.asset_collections:
            return self.asset_collections[step.for_each]
        
        # Check if collection is defined in spec (may be generated_by and not yet populated)
        if self.spec and step.for_each in self.spec.asset_collections:
            # Collection is defined but not yet populated - this is expected for generated_by collections
            return []
        
        # Collection truly not found - warn only for undefined collections
        console.print(f"[yellow]Warning: Collection '{step.for_each}' not found for step '{step.id}'[/yellow]")
        return []
    
    def _populate_collection(self, collection_name: str, items: list[dict[str, Any]]) -> None:
        """
        Populate an asset collection with generated items.
        
        Called when a step with creates_assets completes.
        
        Args:
            collection_name: Name of the collection to populate
            items: List of asset dictionaries to add
        """
        # Ensure each item has an ID
        normalized = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                # If item is a string, wrap it
                item = {"content": item, "name": str(item)[:50]}
            item = dict(item)  # Copy to avoid mutation
            
            if "id" not in item:
                if "name" in item:
                    name_slug = item["name"].lower().replace(" ", "-").replace("'", "")[:30]
                    item["id"] = f"{name_slug}"
                else:
                    item["id"] = f"{collection_name}-{i+1:03d}"
            
            normalized.append(item)
        
        self.asset_collections[collection_name] = normalized
        
        # Update legacy self.assets if this was the first collection
        if not self.assets:
            self.assets = normalized
        
        # Update web UI with new assets
        if self.web_bridge:
            from .web_bridge import AssetInfo
            asset_info_list = []
            for i, asset in enumerate(normalized):
                asset_id = asset.get("id", f"{collection_name}-{i}")
                asset_name = asset.get("name", asset_id)
                asset_info_list.append(AssetInfo(
                    id=asset_id,
                    name=asset_name,
                    data=dict(asset),
                    status="pending",
                    collection=collection_name,
                ))
            
            # Add to existing assets in progress
            progress = self.web_bridge.get_progress()
            progress.assets.extend(asset_info_list)
            progress.total_assets = len(progress.assets)
            self._update_web_progress()
        
        console.print(f"    [green]Created {len(normalized)} assets in collection '{collection_name}'[/green]")
    
    def _collect_outputs(self, base_path: Path, state_dir: Path) -> dict[str, list[Path]]:
        """
        Collect outputs from steps marked with is_output: true.
        
        Returns a dict mapping asset_id -> list of output file paths.
        """
        if not self.spec.output:
            return {}
        
        output_config = self.spec.output
        output_dir = base_path / output_config.directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Find all output steps
        output_steps = [s for s in self.spec.steps if s.is_output]
        
        if not output_steps:
            console.print("[yellow]No steps marked with is_output: true[/yellow]")
            return {}
        
        collected: dict[str, list[Path]] = {}
        total_files = 0
        
        console.print(f"\n[bold]Collecting outputs to {output_config.directory}[/bold]")
        
        for step in output_steps:
            step_dir = state_dir / step.id
            
            if not step_dir.exists():
                continue
            
            # Check for per-asset outputs
            for asset_dir in step_dir.iterdir():
                if not asset_dir.is_dir():
                    continue
                
                asset_id = asset_dir.name
                output_file = asset_dir / "output.json"
                
                if not output_file.exists():
                    continue
                
                try:
                    with open(output_file) as f:
                        data = json.load(f)
                    
                    output_data = data.get("data", {})
                    
                    # Extract file paths from output
                    paths_to_collect = []
                    for key in ["selected_path", "path", "paths", "output_path", "image_path"]:
                        val = output_data.get(key)
                        if isinstance(val, str) and val:
                            paths_to_collect.append(Path(val))
                        elif isinstance(val, list):
                            paths_to_collect.extend(Path(p) for p in val if p)
                    
                    # Copy/symlink each file
                    for src_path in paths_to_collect:
                        if not src_path.is_absolute():
                            src_path = base_path / src_path
                        
                        if not src_path.exists():
                            continue
                        
                        # Determine destination path
                        if output_config.flatten:
                            # All files in root of output dir
                            dest_name = f"{asset_id}_{step.id}_{src_path.name}"
                            dest_path = output_dir / dest_name
                        else:
                            # Organize by asset
                            asset_output_dir = output_dir / asset_id
                            asset_output_dir.mkdir(parents=True, exist_ok=True)
                            dest_path = asset_output_dir / src_path.name
                        
                        # Apply naming pattern if specified
                        if output_config.naming:
                            asset_data = next(
                                (a for a in self.assets if a.get("id") == asset_id),
                                {"id": asset_id}
                            )
                            name_pattern = output_config.naming
                            name_pattern = name_pattern.replace("{asset.id}", asset_id)
                            name_pattern = name_pattern.replace("{asset.name}", asset_data.get("name", asset_id))
                            name_pattern = name_pattern.replace("{step.id}", step.id)
                            ext = src_path.suffix
                            dest_path = dest_path.parent / f"{name_pattern}{ext}"
                        
                        # Copy or symlink
                        if dest_path.exists():
                            dest_path.unlink()
                        
                        if output_config.copy:
                            shutil.copy2(src_path, dest_path)
                        else:
                            dest_path.symlink_to(src_path.resolve())
                        
                        if asset_id not in collected:
                            collected[asset_id] = []
                        collected[asset_id].append(dest_path)
                        total_files += 1
                        
                except (json.JSONDecodeError, IOError) as e:
                    console.print(f"[yellow]Warning: Could not read {output_file}: {e}[/yellow]")
        
        console.print(f"[green]Collected {total_files} files for {len(collected)} assets[/green]")
        
        return collected
    
    def _get_step_action_text(self, step: StepSpec) -> str:
        """
        Generate a concise action description for CLI progress display.
        
        Returns text like:
          - "Generating image with Gemini Imagen"
          - "Generating text with Gemini 2.5 Flash"
          - "Awaiting user selection"
        """
        step_type = step.type.value
        config = step.config or {}
        
        # Map step types to descriptive actions with provider info
        action_map = {
            "generate_image": "Generating image with Gemini Imagen",
            "generate_sprite": "Generating sprite with Gemini Imagen",
            "generate_text": "Generating text with Gemini 2.5 Flash",
            "generate_name": "Generating name with Gemini 2.5 Flash",
            "generate_prompt": "Generating prompt with Gemini 2.5 Flash",
            "research": "Researching with Gemini 2.5 Flash",
            "assess": "Assessing with Gemini Vision",
            "user_select": "Awaiting user selection",
            "user_approve": "Awaiting user approval",
            "review": "Checkpoint review",
            "refine": "Refining output",
            "remove_background": "Removing background",
            "resize": "Resizing image",
            "composite": "Compositing layers",
        }
        
        base_action = action_map.get(step_type, f"Executing {step_type}")
        
        # Add variation info if applicable
        variations = config.get("variations", 1)
        if variations > 1 and step_type in ("generate_image", "generate_sprite"):
            base_action += f" ({variations} variations)"
        
        return base_action
    
    def _get_step_description(
        self, 
        step: StepSpec, 
        asset: dict[str, Any] | None = None,
    ) -> str:
        """
        Generate a human-readable description for a step.
        
        Args:
            step: The step specification
            asset: Optional asset for template substitution (for per-asset steps)
        """
        step_type = step.type.value
        config = step.config or {}
        
        # Get description from config if available
        if "description" in config:
            desc = config["description"]
            # Try to substitute templates
            if asset or self.context:
                desc = substitute_all(desc, self.context, asset, self.step_outputs)
            return desc
        
        # Generate based on step type
        if step_type == "research":
            topic = config.get("topic", "topic")
            return f"Research {topic}"
        elif step_type in ("generate_text", "generate_name", "generate_prompt"):
            prompt = config.get("prompt", "")
            # Substitute templates if we have context
            if prompt and (asset or self.context):
                prompt = substitute_all(prompt, self.context, asset, self.step_outputs)
            if prompt and len(prompt) > 80:
                prompt = prompt[:77] + "..."
            return f"Generate text: {prompt}" if prompt else "Generate text"
        elif step_type == "generate_image":
            prompt = config.get("prompt", "")
            # Substitute templates if we have context
            if prompt and (asset or self.context):
                prompt = substitute_all(prompt, self.context, asset, self.step_outputs)
            if prompt and len(prompt) > 60:
                prompt = prompt[:57] + "..."
            return f"Generate image: {prompt}" if prompt else "Generate image"
        elif step_type == "generate_sprite":
            return "Generate game sprite"
        elif step_type == "assess":
            return "AI assessment of result"
        elif step_type == "user_select":
            return "User selects best option"
        elif step_type == "user_approve":
            return "User approval required"
        elif step_type == "review":
            title = config.get("title", "Checkpoint Review")
            return f"Review checkpoint: {title}"
        elif step_type == "refine":
            return "Refine output"
        elif step_type == "remove_background":
            return "Remove background from image"
        elif step_type == "resize":
            return "Resize image"
        else:
            return f"Execute {step_type}"
    
    def _update_step_status(self, step_id: str, status: str) -> None:
        """Update the status of a step in the web progress."""
        if self.web_bridge:
            progress = self.web_bridge.get_progress()
            for step_info in progress.pipeline_steps:
                if step_info.id == step_id:
                    step_info.status = status
                    break
            self._update_web_progress()
    
    async def run(self) -> ExecutionResult:
        """
        Run the pipeline.
        
        Returns:
            ExecutionResult with statistics and errors
        """
        import time
        from datetime import datetime
        
        start_time = time.time()
        errors = []
        steps_completed = 0
        steps_skipped = 0
        
        try:
            # Load and validate pipeline
            console.print(f"[bold blue]Loading pipeline:[/bold blue] {self.pipeline_path}")
            self.spec = load_pipeline(self.pipeline_path)
            
            console.print(f"[green]✓[/green] Pipeline '{self.spec.name}' loaded")
            
            # Set up directories
            base_path = self.pipeline_path.parent
            state_dir = base_path / self.spec.state.directory
            state_dir.mkdir(parents=True, exist_ok=True)
            
            # Initialize cache manager
            self.cache = CacheManager(state_dir)
            
            # Check if pipeline changed
            pipeline_yaml = self.pipeline_path.read_text()
            if self.cache.check_pipeline_changed(pipeline_yaml):
                console.print("[yellow]Pipeline definition changed - some cache may be invalid[/yellow]")
            
            # Load asset collections (must happen before step info building for per-asset steps)
            self.asset_collections = load_asset_collections(self.spec, base_path)
            
            # Build step info for web UI
            from .web_bridge import StepInfo
            step_infos = []
            for step in self.spec.steps:
                # Get preview asset for this step if it's a per-asset step
                step_assets = self._get_step_assets(step)
                preview_asset = step_assets[0] if step_assets else None
                
                # Generate description from step config (use preview asset for template preview)
                step_desc = self._get_step_description(step, preview_asset)
                step_infos.append(StepInfo(
                    id=step.id,
                    type=step.type.value,
                    description=step_desc,
                    for_each=step.for_each,
                    creates_assets=step.creates_assets,  # Pass creates_assets info
                    output=step.output,  # Field name this step writes to
                    status="pending",
                ))
            
            # Update web progress
            self._update_web_progress(
                pipeline_name=self.spec.name,
                pipeline_description=self.spec.description,
                total_steps=len(self.spec.steps),
                started_at=datetime.now(),
                message="Loading pipeline...",
                pipeline_steps=step_infos,
                context_data=dict(self.spec.context),  # Pass context to web UI
            )
            
            # Print collection info
            total_loaded = sum(len(items) for items in self.asset_collections.values())
            dynamic_collections = [name for name, spec in self.spec.asset_collections.items() 
                                   if spec.generated_by]
            
            if self.asset_collections:
                console.print(f"[green]✓[/green] Asset collections:")
                for name, items in self.asset_collections.items():
                    if items:
                        console.print(f"    {name}: {len(items)} items loaded")
                    else:
                        spec = self.spec.asset_collections.get(name)
                        if spec and spec.generated_by:
                            console.print(f"    {name}: [dim]will be generated by {spec.generated_by}[/dim]")
                        else:
                            console.print(f"    {name}: [dim]empty[/dim]")
            
            # Legacy: set self.assets to the first non-empty collection for backward compatibility
            for items in self.asset_collections.values():
                if items:
                    self.assets = items
                    break
            
            # Build asset info list for web UI (combine all collections)
            from .web_bridge import AssetInfo
            asset_info_list = []
            for collection_name, items in self.asset_collections.items():
                for i, asset in enumerate(items):
                    asset_id = asset.get("id", f"{collection_name}-{i}")
                    asset_name = asset.get("name", asset_id)
                    asset_info_list.append(AssetInfo(
                        id=asset_id,
                        name=asset_name,
                        data=dict(asset),
                        status="pending",
                        collection=collection_name,  # Track which collection this asset belongs to
                    ))
            
            # Update web progress
            self._update_web_progress(
                total_assets=len(asset_info_list),
                message="Assets loaded",
                assets=asset_info_list,
            )
            
            # Initialize providers
            from providers import get_provider_registry
            self.providers = get_provider_registry()
            
            # Set up context
            self.context = dict(self.spec.context)
            self.step_outputs = {}
            
            # Get execution order
            tiers = get_execution_order(self.spec)
            
            # Set web bridge to running phase
            if self.web_bridge:
                from .web_bridge import PipelinePhase
                self.web_bridge.set_phase(PipelinePhase.RUNNING, "Executing pipeline...")
            
            # Execute each tier (tiers must run sequentially, steps within can be parallel)
            for tier_idx, tier in enumerate(tiers):
                console.print(f"\n[bold]Tier {tier_idx}[/bold] ({len(tier)} step{'s' if len(tier) > 1 else ''})")
                
                if len(tier) == 1:
                    # Single step - execute directly
                    step = self.spec.step_index[tier[0]]
                    # Use first asset for per-asset steps (preview)
                    step_assets = self._get_step_assets(step)
                    preview_asset = step_assets[0] if step_assets else None
                    step_desc = self._get_step_description(step, preview_asset)
                    step_prompt = step.config.get("prompt", "") if step.config else ""
                    # Substitute templates in prompt for display
                    if step_prompt:
                        step_prompt = substitute_all(step_prompt, self.context, preview_asset, self.step_outputs)
                    # Get the provider for this step
                    text_provider, image_provider, _, _ = self._get_step_providers(step)
                    current_provider = image_provider if step.type.value in ("generate_image", "generate_sprite") else text_provider
                    self._update_web_progress(
                        current_step=step.id,
                        current_step_type=step.type.value,
                        current_step_description=step_desc,
                        current_step_prompt=step_prompt,
                        current_provider=current_provider,
                        message=f"Running {step.id}...",
                    )
                    self._update_step_status(step.id, "running")
                    
                    result = await self._execute_step(step, base_path, state_dir)
                    
                    if result.cached:
                        steps_skipped += 1
                        self._update_step_status(step.id, "skipped")
                    elif result.success:
                        steps_completed += 1
                        self._update_step_status(step.id, "complete")
                    else:
                        errors.append(f"Step '{tier[0]}' failed: {result.error}")
                        self._update_step_status(step.id, "failed")
                    
                    self._update_web_progress(completed_steps=steps_completed + steps_skipped)
                else:
                    # Multiple steps in tier - execute in parallel
                    semaphore = asyncio.Semaphore(self.tier_parallelism)
                    self._update_web_progress(
                        current_step=f"Tier {tier_idx}",
                        current_step_description=f"Running {len(tier)} steps in parallel",
                        message=f"Running {len(tier)} steps in parallel...",
                    )
                    
                    # Mark all steps as running
                    for step_id in tier:
                        self._update_step_status(step_id, "running")
                    
                    async def run_step_with_semaphore(step_id: str) -> tuple[str, StepResult]:
                        async with semaphore:
                            step = self.spec.step_index[step_id]
                            result = await self._execute_step(step, base_path, state_dir)
                            return step_id, result
                    
                    results = await asyncio.gather(
                        *[run_step_with_semaphore(step_id) for step_id in tier],
                        return_exceptions=True,
                    )
                    
                    for item in results:
                        if isinstance(item, Exception):
                            errors.append(f"Step execution error: {item}")
                        else:
                            step_id, result = item
                            if result.cached:
                                steps_skipped += 1
                                self._update_step_status(step_id, "skipped")
                            elif result.success:
                                steps_completed += 1
                                self._update_step_status(step_id, "complete")
                            else:
                                errors.append(f"Step '{step_id}' failed: {result.error}")
                                self._update_step_status(step_id, "failed")
                    
                    self._update_web_progress(completed_steps=steps_completed + steps_skipped)
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Collect outputs if configured
            collected_outputs = {}
            if self.spec.output and len(errors) == 0:
                collected_outputs = self._collect_outputs(base_path, state_dir)
            
            # Summary
            console.print()
            output_info = ""
            if collected_outputs:
                output_info = f"\nOutputs collected: {sum(len(v) for v in collected_outputs.values())} files → {self.spec.output.directory}"
            console.print(Panel(
                f"[green]Pipeline completed![/green]\n\n"
                f"Assets processed: {len(self.assets)}\n"
                f"Steps completed: {steps_completed}\n"
                f"Steps skipped (cached): {steps_skipped}\n"
                f"Duration: {duration_ms / 1000:.1f}s{output_info}",
                title="Summary",
                border_style="green"
            ))
            
            # Update web bridge to complete phase
            if self.web_bridge:
                from .web_bridge import PipelinePhase
                # Mark all assets as complete
                progress = self.web_bridge.get_progress()
                for asset_info in progress.assets:
                    asset_info.status = "complete"
                self.web_bridge.set_phase(PipelinePhase.COMPLETE, "Pipeline completed!")
                self._update_web_progress(
                    completed_steps=len(self.spec.steps),
                    completed_assets=len(self.assets),
                )
            
            return ExecutionResult(
                success=len(errors) == 0,
                assets_processed=len(self.assets),
                steps_completed=steps_completed,
                steps_skipped=steps_skipped,
                duration_ms=duration_ms,
                errors=errors,
                outputs_collected={k: [str(p) for p in v] for k, v in collected_outputs.items()} if collected_outputs else None,
            )
            
        except Exception as e:
            import traceback
            if self.verbose:
                traceback.print_exc()
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Update web bridge to failed phase
            if self.web_bridge:
                from .web_bridge import PipelinePhase
                self.web_bridge.set_phase(PipelinePhase.FAILED, f"Pipeline failed: {e}")
                self._update_web_progress(errors=[str(e)])
            
            return ExecutionResult(
                success=False,
                assets_processed=0,
                steps_completed=steps_completed,
                steps_skipped=steps_skipped,
                duration_ms=duration_ms,
                errors=[str(e)],
            )
    
    async def _execute_step(
        self,
        step: StepSpec,
        base_path: Path,
        state_dir: Path,
    ) -> StepResult:
        """Execute a single step."""
        
        # Determine cache setting with smart defaults
        cache_setting = step.cache
        if cache_setting is False:
            # Explicit false
            pass
        elif cache_setting is True or cache_setting == "skip_existing":
            pass
        else:
            # Smart defaults
            if step.for_each:
                cache_setting = "skip_existing"
            else:
                cache_setting = True
        
        # Check condition
        if step.condition:
            should_run = evaluate_condition(step.condition, {
                "context": self.context,
                "ctx": self.context,
                **self.step_outputs,
            })
            if not should_run:
                console.print(f"  [dim]Skipping {step.id} (condition not met)[/dim]")
                return StepResult(success=True, cached=True)
        
        # Handle per-asset vs global steps
        step_assets = self._get_step_assets(step)
        if step.for_each and step_assets:
            return await self._execute_per_asset(step, base_path, state_dir, cache_setting, step_assets)
        else:
            return await self._execute_global(step, base_path, state_dir, cache_setting)
    
    async def _execute_global(
        self,
        step: StepSpec,
        base_path: Path,
        state_dir: Path,
        cache_setting: bool | str,
    ) -> StepResult:
        """Execute a global (non-per-asset) step."""
        
        # Check cache
        if should_skip_step(self.cache, step.id, cache_setting):
            cached_output = self.cache.get_cached_output(step.id)
            if cached_output is not None:
                console.print(f"  [dim]{step.id}: cached[/dim]")
                self.step_outputs[step.id] = cached_output
                # Also store under writes_to alias if specified
                if step.output:
                    self.step_outputs[step.output] = cached_output
                
                # Restore asset collection if this step creates assets
                if step.creates_assets:
                    items = self._extract_asset_list(cached_output, step)
                    if items:
                        self._populate_collection(step.creates_assets, items)
                
                return StepResult(success=True, cached=True, output=cached_output)
        
        action_text = self._get_step_action_text(step)
        console.print(f"  [cyan]{step.id}[/cyan] - {action_text}...")
        
        # Get executor
        try:
            executor = get_executor(step.type.value)
        except ValueError:
            console.print(f"    [red]No executor for step type: {step.type.value}[/red]")
            return StepResult(success=False, error=f"No executor for {step.type.value}")
        
        # Get resolved providers for this step
        text_provider, image_provider, text_model, image_model = self._get_step_providers(step)
        
        # Build context
        ctx = ExecutorContext(
            pipeline_name=self.spec.name,
            base_path=base_path,
            state_dir=state_dir,
            context=self.context,
            step_outputs=self.step_outputs,
            providers=self.providers,
            text_provider=text_provider,
            image_provider=image_provider,
            text_model=text_model,
            image_model=image_model,
        )
        
        # Substitute templates in config
        config = substitute_all(
            step.config,
            self.context,
            None,
            self.step_outputs,
        )
        config["_step_id"] = step.id
        
        # Execute
        result = await executor.execute(config, ctx)
        
        if result.success:
            console.print(f"    [green]✓[/green] Done ({result.duration_ms}ms)")
            self.step_outputs[step.id] = result.output
            # Also store under writes_to alias if specified
            if step.output:
                self.step_outputs[step.output] = result.output
            
            # Cache the output (include prompt for history display)
            self.cache.cache_step_output(
                step.id,
                result.output,
                output_paths=result.output_paths,
                prompt=result.prompt,
            )
            
            # Handle creates_assets - populate the target collection
            if step.creates_assets:
                items = self._extract_asset_list(result.output, step)
                if items:
                    self._populate_collection(step.creates_assets, items)
                else:
                    console.print(f"    [yellow]Warning: Step '{step.id}' has creates_assets but output didn't contain a list[/yellow]")
        else:
            console.print(f"    [red]✗[/red] Failed: {result.error}")
        
        return result
    
    def _extract_asset_list(self, output: Any, step: StepSpec) -> list[dict[str, Any]]:
        """
        Extract a list of assets from step output.
        
        Handles various output formats:
        - List directly
        - Dict with "items" or "assets" key
        - Text content that can be parsed as JSON or structured format
        
        Args:
            output: The step output
            step: The step specification (for config hints)
            
        Returns:
            List of asset dicts, or empty list if extraction fails
        """
        # If output is already a list
        if isinstance(output, list):
            return output
        
        # If output is a dict
        if isinstance(output, dict):
            # Check for common list keys
            for key in ["items", "assets", "list", "data", "results"]:
                if key in output and isinstance(output[key], list):
                    return output[key]
            
            # Check for "content" that might be parseable
            if "content" in output:
                content = output["content"]
                if isinstance(content, list):
                    return content
                if isinstance(content, str):
                    return self._parse_content_as_list(content)
        
        # If output is a string, try to parse it
        if isinstance(output, str):
            return self._parse_content_as_list(output)
        
        return []
    
    def _parse_content_as_list(self, content: str) -> list[dict[str, Any]]:
        """
        Parse text content to extract a list of items.
        
        Tries:
        1. JSON parsing
        2. YAML parsing
        3. Simple line-by-line parsing for numbered lists
        
        Args:
            content: Text content to parse
            
        Returns:
            List of asset dicts, or empty list if parsing fails
        """
        import re
        
        # Try JSON
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ["items", "assets", "list", "data"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Try to find JSON array in content
        json_match = re.search(r'\[\s*\{.*?\}\s*\]', content, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, ValueError):
                pass
        
        # Try YAML
        try:
            import yaml
            data = yaml.safe_load(content)
            if isinstance(data, list):
                return data
        except:
            pass
        
        # Try parsing numbered list (1. Name - Description)
        lines = content.strip().split('\n')
        items = []
        current_item = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Match patterns like "1. Name" or "- Name" or "* Name"
            numbered_match = re.match(r'^(?:\d+\.|\-|\*)\s*(.+?)(?:\s*[-:]\s*(.+))?$', line)
            if numbered_match:
                name = numbered_match.group(1).strip()
                desc = numbered_match.group(2).strip() if numbered_match.group(2) else ""
                items.append({"name": name, "description": desc})
        
        return items
    
    async def _execute_per_asset(
        self,
        step: StepSpec,
        base_path: Path,
        state_dir: Path,
        cache_setting: bool | str,
        step_assets: list[dict[str, Any]] | None = None,
    ) -> StepResult:
        """Execute a per-asset step with parallel processing."""
        
        # Use provided assets or fall back to self.assets
        assets_to_process = step_assets if step_assets is not None else self.assets
        
        # Generate descriptive action text
        action_text = self._get_step_action_text(step)
        asset_count = len(assets_to_process)
        asset_label = "asset" if asset_count == 1 else "assets"
        collection_name = step.for_each or "assets"
        
        console.print(f"  [cyan]{step.id}[/cyan] - {action_text} ({asset_count} {collection_name})")
        self._update_web_progress(current_step=step.id, message=f"{action_text}...")
        
        # Get pending assets (for skip_existing)
        if cache_setting == "skip_existing":
            all_ids = [a.get("id", f"asset-{i}") for i, a in enumerate(assets_to_process)]
            pending_ids = self.cache.get_pending_assets(step.id, all_ids)
            pending_assets = [
                (i, a) for i, a in enumerate(assets_to_process)
                if a.get("id", f"asset-{i}") in pending_ids
            ]
            
            skipped = len(assets_to_process) - len(pending_assets)
            if skipped > 0:
                console.print(f"    [dim]Skipping {skipped} cached assets[/dim]")
        else:
            pending_assets = list(enumerate(assets_to_process))
        
        if not pending_assets:
            return StepResult(success=True, cached=True)
        
        # Get executor
        try:
            executor = get_executor(step.type.value)
        except ValueError:
            console.print(f"    [red]No executor for step type: {step.type.value}[/red]")
            return StepResult(success=False, error=f"No executor for {step.type.value}")
        
        # Check if this step needs user interaction (cannot parallelize if so)
        needs_user_interaction = (
            (step.until == "approved" and not self.auto_approve) or
            (step.select == "user" and not self.auto_approve) or
            (step.variations and step.variations > 1 and not self.auto_approve)
        )
        
        # Use parallelism only for non-interactive steps
        parallelism = 1 if needs_user_interaction else self.asset_parallelism
        semaphore = asyncio.Semaphore(parallelism)
        
        # Results tracking (thread-safe with lock)
        results: list[StepResult] = []
        results_lock = asyncio.Lock()
        completed_count = [0]  # Use list to allow mutation in nested function
        
        async def process_asset(
            asset_idx: int,
            asset: dict[str, Any],
            progress: Progress,
            task: Any,
        ) -> None:
            """Process a single asset."""
            nonlocal completed_count
            async with semaphore:
                asset_id = asset.get("id", f"asset-{asset_idx}")
                asset_name = asset.get("name", asset_id)
                
                # Mark asset as processing
                self._update_asset_status(asset_id, "processing")
                
                # Get asset-specific description and prompt
                step_desc = self._get_step_description(step, asset)
                step_prompt = step.config.get("prompt", "") if step.config else ""
                if step_prompt:
                    step_prompt = substitute_all(step_prompt, self.context, asset, self.step_outputs)
                
                # Update web progress with current asset data and its prompt
                self._update_web_progress(
                    current_asset=asset_name,
                    current_asset_data=dict(asset),  # Pass full asset info
                    current_step_description=step_desc,
                    current_step_prompt=step_prompt,
                )
                
                progress.update(task, description=f"    {asset_name}")
                
                # Get asset-aware step outputs for template substitution
                asset_aware_outputs = get_asset_aware_step_outputs(
                    self.step_outputs,
                    self.spec.step_index,
                    asset,
                )
                
                # Get resolved providers for this step
                text_provider, image_provider, text_model, image_model = self._get_step_providers(step)
                
                # Build context
                ctx = ExecutorContext(
                    pipeline_name=self.spec.name,
                    base_path=base_path,
                    state_dir=state_dir,
                    context=self.context,
                    step_outputs=asset_aware_outputs,  # Use asset-aware outputs
                    asset=asset,
                    asset_index=asset_idx,
                    total_assets=len(assets_to_process),
                    providers=self.providers,
                    text_provider=text_provider,
                    image_provider=image_provider,
                    text_model=text_model,
                    image_model=image_model,
                )
                
                # Substitute templates in config (using asset-aware outputs)
                config = substitute_all(
                    step.config,
                    self.context,
                    asset,
                    asset_aware_outputs,
                )
                config["_step_id"] = step.id
                
                # Handle variations at step level
                if step.variations:
                    config["variations"] = step.variations
                
                # Handle until: approved loop
                if step.until == "approved":
                    if needs_user_interaction:
                        with pause_progress(progress):
                            result = await self._execute_until_approved(
                                step, executor, config, ctx, asset_name
                            )
                    else:
                        result = await self._execute_until_approved(
                            step, executor, config, ctx, asset_name
                        )
                else:
                    # Normal execution with retry
                    try:
                        result = await retry_async(
                            executor.execute,
                            config,
                            ctx,
                            config=API_RETRY_CONFIG,
                        )
                    except Exception as e:
                        result = StepResult(success=False, error=str(e))
                    
                    if result.success:
                        # Handle variations and selection (select: user or multiple variations)
                        needs_selection = (
                            (step.select == "user" and result.variations) or
                            (result.variations and len(result.variations) > 1)
                        )
                        if needs_selection and not self.auto_approve:
                            with pause_progress(progress):
                                result = await self._handle_variations(
                                    step, result, ctx, asset_name, executor, config
                                )
                
                if result.success:
                    # Cache the output (include prompt for history display)
                    self.cache.cache_step_output(
                        step.id,
                        result.output,
                        asset_id=asset_id,
                        output_paths=result.output_paths,
                        prompt=result.prompt,
                    )
                    
                    # Store per-asset output (with lock for thread safety)
                    async with results_lock:
                        if step.id not in self.step_outputs:
                            self.step_outputs[step.id] = {"assets": {}}
                        self.step_outputs[step.id]["assets"][asset_id] = result.output
                    
                    # Update asset data if step writes to a specific field
                    if step.output:
                        # Extract the text content from the output
                        output_value = result.output
                        if isinstance(output_value, dict):
                            output_value = output_value.get("content", output_value)
                        self._update_asset_data(asset_id, step.output, output_value)
                    
                    # Mark asset as complete
                    self._update_asset_status(asset_id, "complete")
                else:
                    # Mark asset as failed
                    self._update_asset_status(asset_id, "failed")
                
                async with results_lock:
                    results.append(result)
                    completed_count[0] += 1
                    # Update web progress
                    self._update_web_progress(completed_assets=completed_count[0])
                
                progress.update(task, advance=1)
        
        # Process assets with descriptive progress
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"    {action_text}", total=len(pending_assets))
            
            # Create all tasks
            tasks = [
                process_asset(asset_idx, asset, progress, task)
                for asset_idx, asset in pending_assets
            ]
            
            # Run with parallelism controlled by semaphore
            gather_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Check for exceptions in gather results
            for i, res in enumerate(gather_results):
                if isinstance(res, Exception):
                    console.print(f"    [red]Task {i} exception: {res}[/red]")
                    import traceback
                    traceback.print_exception(type(res), res, res.__traceback__)
        
        # Check if all succeeded
        failed = [r for r in results if not r.success]
        if failed:
            return StepResult(
                success=False,
                error=f"{len(failed)} assets failed",
            )
        
        parallel_note = f" (parallel={parallelism})" if parallelism > 1 else ""
        console.print(f"    [green]✓[/green] Completed {len(pending_assets)} assets{parallel_note}")
        return StepResult(success=True)
    
    async def _execute_until_approved(
        self,
        step: StepSpec,
        executor: StepExecutor,
        config: dict[str, Any],
        ctx: ExecutorContext,
        asset_name: str,
    ) -> StepResult:
        """Execute a step in an approval loop until user approves or max attempts."""
        
        max_attempts = step.max_attempts
        approve_executor = get_executor("user_approve")
        
        for attempt in range(1, max_attempts + 1):
            console.print(f"    [dim]Attempt {attempt}/{max_attempts}[/dim]")
            
            # Generate
            result = await executor.execute(config, ctx)
            
            if not result.success:
                return result
            
            # Auto-approve mode
            if self.auto_approve:
                return result
            
            # Show to user for approval
            approve_ctx = ExecutorContext(
                pipeline_name=ctx.pipeline_name,
                base_path=ctx.base_path,
                state_dir=ctx.state_dir,
                context=ctx.context,
                step_outputs={step.id: result.output},
                asset=ctx.asset,
                asset_index=ctx.asset_index,
                total_assets=ctx.total_assets,
                providers=ctx.providers,
                text_provider=ctx.text_provider,
                image_provider=ctx.image_provider,
                text_model=ctx.text_model,
                image_model=ctx.image_model,
            )
            
            approve_result = await approve_executor.execute(
                {"prompt": f"Approve result for {asset_name}?"},
                approve_ctx,
            )
            
            if approve_result.success and approve_result.output:
                if approve_result.output.get("approved", False):
                    # User approved!
                    if result.output:
                        result.output["approved_attempt"] = attempt
                    return result
                else:
                    # Rejected - will regenerate
                    console.print(f"    [yellow]Regenerating...[/yellow]")
                    continue
            else:
                # Approval step failed - treat as approved to avoid infinite loop
                return result
        
        # Hit max attempts
        console.print(f"    [yellow]Max attempts ({max_attempts}) reached[/yellow]")
        if result.output:
            result.output["max_attempts_reached"] = True
        return result
    
    async def _handle_variations(
        self,
        step: StepSpec,
        result: StepResult,
        ctx: ExecutorContext,
        asset_name: str,
        executor: StepExecutor,
        config: dict[str, Any],
        max_regenerations: int = 3,
    ) -> StepResult:
        """Handle variation selection for a step result."""
        
        if self.auto_approve:
            # Auto-select first variation
            result.selected_index = 0
            if result.output:
                result.output["selected_index"] = 0
                if result.variations:
                    result.output["selected_path"] = result.variations[0]
            return result
        
        regeneration_count = 0
        
        while regeneration_count < max_regenerations:
            # Use user_select executor for CLI selection
            select_executor = get_executor("user_select")
            
            # Build selection context
            select_ctx = ExecutorContext(
                pipeline_name=ctx.pipeline_name,
                base_path=ctx.base_path,
                state_dir=ctx.state_dir,
                context=ctx.context,
                step_outputs={step.id: result.output},
                asset=ctx.asset,
                asset_index=ctx.asset_index,
                total_assets=ctx.total_assets,
                providers=ctx.providers,
                text_provider=ctx.text_provider,
                image_provider=ctx.image_provider,
                text_model=ctx.text_model,
                image_model=ctx.image_model,
            )
            
            select_result = await select_executor.execute(
                {
                    "prompt": f"Select best for {asset_name}",
                    "options_from": step.id,
                },
                select_ctx,
            )
            
            if select_result.success and select_result.output:
                action = select_result.output.get("action")
                
                if action == "regenerate":
                    regeneration_count += 1
                    console.print(f"[cyan]Regenerating... (attempt {regeneration_count}/{max_regenerations})[/cyan]")
                    
                    # Re-run the generation step
                    result = await executor.execute(config, ctx)
                    
                    if not result.success:
                        console.print(f"[red]Regeneration failed: {result.error}[/red]")
                        return result
                    
                    # If no variations in new result, just return it
                    if not result.variations or len(result.variations) <= 1:
                        return result
                    
                    # Loop back to selection
                    continue
                else:
                    # User made a selection
                    result.selected_index = select_result.output.get("selected_index", 0)
                    if result.output:
                        result.output["selected_index"] = result.selected_index
                        result.output["selected_path"] = select_result.output.get("selected_path")
                    return result
            else:
                # Selection failed
                return result
        
        # Hit max regenerations - use first option
        console.print(f"[yellow]Max regenerations ({max_regenerations}) reached - using first option[/yellow]")
        result.selected_index = 0
        if result.output:
            result.output["selected_index"] = 0
            if result.variations:
                result.output["selected_path"] = result.variations[0]
        
        return result


async def run_pipeline(
    pipeline_path: Path | str,
    input_override: Path | str | None = None,
    auto_approve: bool = False,
    verbose: bool = False,
    asset_parallelism: int = DEFAULT_ASSET_PARALLELISM,
    tier_parallelism: int = DEFAULT_TIER_PARALLELISM,
    web_bridge: Any = None,
) -> ExecutionResult:
    """
    Convenience function to run a pipeline.
    
    Args:
        pipeline_path: Path to pipeline YAML file
        input_override: Optional override for asset input file
        auto_approve: Skip human approval steps
        verbose: Show detailed output
        asset_parallelism: Max concurrent assets per step (default 3)
        tier_parallelism: Max concurrent steps in same tier (default 4)
        web_bridge: Optional WebApprovalBridge for web mode
        
    Returns:
        ExecutionResult
    """
    executor = PipelineExecutor(
        pipeline_path=pipeline_path,
        input_override=input_override,
        auto_approve=auto_approve,
        verbose=verbose,
        asset_parallelism=asset_parallelism,
        tier_parallelism=tier_parallelism,
        web_bridge=web_bridge,
    )
    return await executor.run()
