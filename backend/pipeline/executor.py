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
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from .asset_loader import load_assets
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
        self.assets: list[dict[str, Any]] = []
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
            
            # Build step info for web UI
            from .web_bridge import StepInfo
            step_infos = []
            # Use first asset for preview substitution if available
            preview_asset = self.assets[0] if self.assets else None
            for step in self.spec.steps:
                # Generate description from step config (use preview asset for template preview)
                step_desc = self._get_step_description(step, preview_asset if step.for_each == "asset" else None)
                step_infos.append(StepInfo(
                    id=step.id,
                    type=step.type.value,
                    description=step_desc,
                    for_each=step.for_each,
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
            
            # Load assets
            if self.input_override:
                # Override from_file
                self.spec.assets.from_file = str(self.input_override)
            
            self.assets = load_assets(self.spec, base_path)
            console.print(f"[green]✓[/green] Loaded {len(self.assets)} assets")
            
            # Build asset info list for web UI
            from .web_bridge import AssetInfo
            asset_info_list = []
            for i, asset in enumerate(self.assets):
                asset_id = asset.get("id", f"asset-{i}")
                asset_name = asset.get("name", asset_id)
                asset_info_list.append(AssetInfo(
                    id=asset_id,
                    name=asset_name,
                    data=dict(asset),
                    status="pending",
                ))
            
            # Update web progress
            self._update_web_progress(
                total_assets=len(self.assets),
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
                    preview_asset = self.assets[0] if self.assets and step.for_each == "asset" else None
                    step_desc = self._get_step_description(step, preview_asset)
                    step_prompt = step.config.get("prompt", "") if step.config else ""
                    # Substitute templates in prompt for display
                    if step_prompt:
                        step_prompt = substitute_all(step_prompt, self.context, preview_asset, self.step_outputs)
                    self._update_web_progress(
                        current_step=step.id,
                        current_step_type=step.type.value,
                        current_step_description=step_desc,
                        current_step_prompt=step_prompt,
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
            
            # Summary
            console.print()
            console.print(Panel(
                f"[green]Pipeline completed![/green]\n\n"
                f"Assets processed: {len(self.assets)}\n"
                f"Steps completed: {steps_completed}\n"
                f"Steps skipped (cached): {steps_skipped}\n"
                f"Duration: {duration_ms / 1000:.1f}s",
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
        if step.for_each == "asset":
            return await self._execute_per_asset(step, base_path, state_dir, cache_setting)
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
                return StepResult(success=True, cached=True, output=cached_output)
        
        action_text = self._get_step_action_text(step)
        console.print(f"  [cyan]{step.id}[/cyan] - {action_text}...")
        
        # Get executor
        try:
            executor = get_executor(step.type.value)
        except ValueError:
            console.print(f"    [red]No executor for step type: {step.type.value}[/red]")
            return StepResult(success=False, error=f"No executor for {step.type.value}")
        
        # Build context
        ctx = ExecutorContext(
            pipeline_name=self.spec.name,
            base_path=base_path,
            state_dir=state_dir,
            context=self.context,
            step_outputs=self.step_outputs,
            providers=self.providers,
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
            
            # Cache the output
            self.cache.cache_step_output(
                step.id,
                result.output,
                output_paths=result.output_paths,
            )
        else:
            console.print(f"    [red]✗[/red] Failed: {result.error}")
        
        return result
    
    async def _execute_per_asset(
        self,
        step: StepSpec,
        base_path: Path,
        state_dir: Path,
        cache_setting: bool | str,
    ) -> StepResult:
        """Execute a per-asset step with parallel processing."""
        
        # Generate descriptive action text
        action_text = self._get_step_action_text(step)
        asset_count = len(self.assets)
        asset_label = "asset" if asset_count == 1 else "assets"
        
        console.print(f"  [cyan]{step.id}[/cyan] - {action_text} ({asset_count} {asset_label})")
        self._update_web_progress(current_step=step.id, message=f"{action_text}...")
        
        # Get pending assets (for skip_existing)
        if cache_setting == "skip_existing":
            all_ids = [a.get("id", f"asset-{i}") for i, a in enumerate(self.assets)]
            pending_ids = self.cache.get_pending_assets(step.id, all_ids)
            pending_assets = [
                (i, a) for i, a in enumerate(self.assets)
                if a.get("id", f"asset-{i}") in pending_ids
            ]
            
            skipped = len(self.assets) - len(pending_assets)
            if skipped > 0:
                console.print(f"    [dim]Skipping {skipped} cached assets[/dim]")
        else:
            pending_assets = list(enumerate(self.assets))
        
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
                
                # Build context
                ctx = ExecutorContext(
                    pipeline_name=self.spec.name,
                    base_path=base_path,
                    state_dir=state_dir,
                    context=self.context,
                    step_outputs=asset_aware_outputs,  # Use asset-aware outputs
                    asset=asset,
                    asset_index=asset_idx,
                    total_assets=len(self.assets),
                    providers=self.providers,
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
                    # Cache the output
                    self.cache.cache_step_output(
                        step.id,
                        result.output,
                        asset_id=asset_id,
                        output_paths=result.output_paths,
                    )
                    
                    # Store per-asset output (with lock for thread safety)
                    async with results_lock:
                        if step.id not in self.step_outputs:
                            self.step_outputs[step.id] = {"assets": {}}
                        self.step_outputs[step.id]["assets"][asset_id] = result.output
                    
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
