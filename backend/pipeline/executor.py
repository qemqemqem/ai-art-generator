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
        """
        self.pipeline_path = Path(pipeline_path)
        self.input_override = Path(input_override) if input_override else None
        self.auto_approve = auto_approve
        self.verbose = verbose
        self.asset_parallelism = asset_parallelism
        self.tier_parallelism = tier_parallelism
        
        # Will be set during run()
        self.spec: PipelineSpec | None = None
        self.assets: list[dict[str, Any]] = []
        self.cache: CacheManager | None = None
        self.providers: Any = None
        
        # Execution state
        self.context: dict[str, Any] = {}
        self.step_outputs: dict[str, Any] = {}
    
    async def run(self) -> ExecutionResult:
        """
        Run the pipeline.
        
        Returns:
            ExecutionResult with statistics and errors
        """
        import time
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
            
            # Load assets
            if self.input_override:
                # Override from_file
                self.spec.assets.from_file = str(self.input_override)
            
            self.assets = load_assets(self.spec, base_path)
            console.print(f"[green]✓[/green] Loaded {len(self.assets)} assets")
            
            # Initialize providers
            from providers import get_provider_registry
            self.providers = get_provider_registry()
            
            # Set up context
            self.context = dict(self.spec.context)
            self.step_outputs = {}
            
            # Get execution order
            tiers = get_execution_order(self.spec)
            
            # Execute each tier (tiers must run sequentially, steps within can be parallel)
            for tier_idx, tier in enumerate(tiers):
                console.print(f"\n[bold]Tier {tier_idx}[/bold] ({len(tier)} step{'s' if len(tier) > 1 else ''})")
                
                if len(tier) == 1:
                    # Single step - execute directly
                    step = self.spec.step_index[tier[0]]
                    result = await self._execute_step(step, base_path, state_dir)
                    
                    if result.cached:
                        steps_skipped += 1
                    elif result.success:
                        steps_completed += 1
                    else:
                        errors.append(f"Step '{tier[0]}' failed: {result.error}")
                else:
                    # Multiple steps in tier - execute in parallel
                    semaphore = asyncio.Semaphore(self.tier_parallelism)
                    
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
                            elif result.success:
                                steps_completed += 1
                            else:
                                errors.append(f"Step '{step_id}' failed: {result.error}")
            
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
        
        console.print(f"  [cyan]{step.id}[/cyan] ({step.type.value})...")
        
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
        
        console.print(f"  [cyan]{step.id}[/cyan] ({step.type.value}) - {len(self.assets)} assets")
        
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
        
        async def process_asset(
            asset_idx: int,
            asset: dict[str, Any],
            progress: Progress,
            task: Any,
        ) -> None:
            """Process a single asset."""
            async with semaphore:
                asset_id = asset.get("id", f"asset-{asset_idx}")
                asset_name = asset.get("name", asset_id)
                
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
                
                async with results_lock:
                    results.append(result)
                
                progress.update(task, advance=1)
        
        # Process assets
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"    Processing", total=len(pending_assets))
            
            # Create all tasks
            tasks = [
                process_asset(asset_idx, asset, progress, task)
                for asset_idx, asset in pending_assets
            ]
            
            # Run with parallelism controlled by semaphore
            await asyncio.gather(*tasks, return_exceptions=True)
        
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
    )
    return await executor.run()
