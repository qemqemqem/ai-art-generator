#!/usr/bin/env python3
"""
ArtGen CLI - Command-line interface for AI art generation pipelines.

Usage:
    artgen run pipeline.yaml              # Run a pipeline
    artgen validate pipeline.yaml         # Validate without running
    artgen show pipeline.yaml             # Show pipeline structure
    artgen clean pipeline.yaml            # Clear cached data
    artgen list                           # List pipelines in current directory
"""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from app.config import reload_config
from pipeline.logging_config import setup_logging

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="artgen")
def cli():
    """ArtGen - AI Art Generation Pipeline Runner"""
    pass


@cli.command()
@click.argument("pipeline", type=click.Path(exists=True))
@click.option("--env", "-e", "env_path", type=click.Path(exists=True),
              help="Path to .env file")
@click.option("--input", "-i", "input_file", type=click.Path(exists=True),
              help="Override asset input file")
@click.option("--clean-state", is_flag=True,
              help="Delete all cached outputs before running (forces full regeneration)")
@click.option("--from-step", "-F", "from_step",
              help="Re-run from this step onward (invalidates it and all downstream steps)")
@click.option("--auto-approve", "-y", is_flag=True,
              help="Auto-approve all selections (no human interaction)")
@click.option("--verbose", "-v", is_flag=True,
              help="Show detailed output")
@click.option("--dry-run", is_flag=True,
              help="Show what would be executed without running")
@click.option("--parallel", "-p", default=20, type=int,
              help="Max parallel assets per step (default: 20)")
@click.option("--skip-validation", is_flag=True,
              help="Skip pre-run validation")
@click.option("--web", "-w", is_flag=True,
              help="Enable web-based interactive mode (opens browser)")
@click.option("--port", default=8080, type=int,
              help="Port for web server (default: 8080)")
@click.option("--no-browser", is_flag=True,
              help="Don't auto-open browser (with --web)")
@click.option("--log-file", type=click.Path(), default=None,
              help="Write detailed logs to file (captures all provider/library output)")
@click.option("--regenerate-missing", is_flag=True,
              help="Detect deleted output files and fully regenerate those assets from scratch")
def run(
    pipeline: str,
    env_path: str | None,
    input_file: str | None,
    clean_state: bool,
    from_step: str | None,
    auto_approve: bool,
    verbose: bool,
    dry_run: bool,
    parallel: int,
    skip_validation: bool,
    web: bool,
    port: int,
    no_browser: bool,
    log_file: str | None,
    regenerate_missing: bool,
):
    """Run an ArtGen pipeline.

    \b
    Caching:
      By default, completed steps/assets are skipped on re-run (resume mode).
      To force a full regeneration, use --clean-state to wipe all cached data.
      To re-run from a specific step onward, use --from-step step_id.
      To regenerate specific assets whose output you deleted, use
      --regenerate-missing (requires a previous successful run).
      To selectively re-run specific steps or assets, use `artgen clean`
      first (e.g. `artgen clean pipeline.yaml -s step_id -a asset_id`).
      You can also set `cache: false` on individual steps in the YAML.
    """
    
    pipeline_path = Path(pipeline)
    
    # Add backend to path
    backend_path = Path(__file__).parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))

    # Set up logging early (before any providers are imported)
    # State dir is resolved later, so pass log_file if explicit
    log_path = setup_logging(verbose=verbose, log_file=log_file)
    if log_path:
        console.print(f"[dim]Logging to: {log_path}[/dim]")

    # Load env (explicit path takes precedence, otherwise auto-discovery)
    if env_path:
        os.environ["ARTGEN_ENV_FILE"] = env_path
    reload_config(env_path)

    if clean_state:
        from pipeline.spec_parser import load_pipeline

        spec = load_pipeline(pipeline_path)
        state_dir = pipeline_path.parent / spec.state.directory
        if state_dir.exists():
            shutil.rmtree(state_dir)
            console.print(f"[yellow]Cleared state directory:[/yellow] {state_dir}")
        else:
            console.print(f"[dim]State directory not found:[/dim] {state_dir}")

    if from_step and not clean_state:
        from pipeline.spec_parser import load_pipeline, get_downstream_steps
        from pipeline.cache import CacheManager

        spec = load_pipeline(pipeline_path)
        state_dir = pipeline_path.parent / spec.state.directory
        downstream = get_downstream_steps(spec, from_step)

        if state_dir.exists():
            cache = CacheManager(state_dir)
            count = cache.invalidate_steps(downstream)
            console.print(
                f"[yellow]Re-running from '{from_step}'[/yellow] — "
                f"invalidated {count} cache entries for: {', '.join(sorted(downstream))}"
            )
        else:
            console.print(f"[dim]No cached state to invalidate[/dim]")

    if regenerate_missing and not clean_state:
        missing_assets = _detect_missing_assets(pipeline_path)
        if missing_assets:
            _invalidate_missing_assets(pipeline_path, missing_assets, auto_approve)

    if dry_run:
        # Just show the plan
        show_pipeline_plan(pipeline_path)
        return
    
    # Run validation first
    if not skip_validation:
        from pipeline.validation import validate_all, print_validation_result
        
        result, spec = validate_all(pipeline_path, check_env=True)
        
        if not result.valid:
            print_validation_result(result, verbose=verbose)
            sys.exit(1)
        elif result.warnings and verbose:
            print_validation_result(result, verbose=True)
    
    # Web mode
    if web:
        _run_with_web(
            pipeline_path=pipeline_path,
            input_file=input_file,
            auto_approve=auto_approve,
            verbose=verbose,
            parallel=parallel,
            port=port,
            open_browser=not no_browser,
        )
        return
    
    # CLI mode
    console.print()
    console.print(Panel(
        f"[bold]ArtGen Pipeline Runner[/bold]\n\n"
        f"Pipeline: {pipeline_path.name}\n"
        f"Auto-approve: {'Yes' if auto_approve else 'No'}\n"
        f"Parallelism: {parallel}",
        border_style="blue"
    ))
    console.print()
    
    from pipeline.executor import run_pipeline
    
    result = asyncio.run(run_pipeline(
        pipeline_path=pipeline_path,
        input_override=input_file,
        auto_approve=auto_approve,
        verbose=verbose,
        asset_parallelism=parallel,
    ))
    
    if not result.success:
        console.print("\n[red]Pipeline failed:[/red]")
        for error in result.errors:
            console.print(f"  • {error}")
        sys.exit(1)


def _run_with_web(
    pipeline_path: Path,
    input_file: str | None,
    auto_approve: bool,
    verbose: bool,
    parallel: int,
    port: int,
    open_browser: bool,
):
    """Run pipeline with web-based interactive mode."""
    from pipeline.web_server import WebServer, set_base_path
    from pipeline.web_bridge import get_bridge, reset_bridge, PipelinePhase
    from pipeline.executor import run_pipeline
    
    # Reset the bridge for this run
    bridge = reset_bridge()
    
    # Start web server
    base_path = pipeline_path.parent
    server = WebServer(port=port)
    
    console.print()
    console.print(Panel(
        f"[bold]ArtGen Pipeline Runner (Web Mode)[/bold]\n\n"
        f"Pipeline: {pipeline_path.name}\n"
        f"Web UI: http://127.0.0.1:{port}\n"
        f"Parallelism: {parallel}",
        border_style="blue"
    ))
    console.print()
    
    console.print(f"[cyan]Starting web server on port {port}...[/cyan]")
    server.start(base_path=base_path, open_browser=open_browser)
    console.print(f"[green]✓[/green] Web server started: {server.url}")
    
    if open_browser:
        console.print("[dim]Browser opened - approvals will appear there[/dim]")
    
    console.print()
    
    try:
        # Run pipeline with web bridge active
        bridge.set_phase(PipelinePhase.LOADING, "Loading pipeline...")
        
        result = asyncio.run(run_pipeline(
            pipeline_path=pipeline_path,
            input_override=input_file,
            auto_approve=auto_approve,
            verbose=verbose,
            asset_parallelism=parallel,
            web_bridge=bridge,
        ))
        
        if result.success:
            bridge.set_phase(PipelinePhase.COMPLETE, "Pipeline completed successfully")
            console.print("\n[green]Pipeline completed![/green]")
        else:
            bridge.update_progress(errors=result.errors)
            bridge.set_phase(PipelinePhase.FAILED, "Pipeline failed")
            console.print("\n[red]Pipeline failed:[/red]")
            for error in result.errors:
                console.print(f"  • {error}")
        
        # Wait for browser close or user shutdown
        console.print("\n[dim]Waiting for browser close or Ctrl+C to exit...[/dim]")
        
        try:
            asyncio.run(bridge.wait_for_shutdown())
        except KeyboardInterrupt:
            pass
        
    finally:
        console.print("\n[dim]Shutting down web server...[/dim]")
        server.stop()
        console.print("[green]✓[/green] Done")


@cli.command()
@click.argument("pipeline", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show all warnings")
@click.option("--skip-env", is_flag=True, help="Skip environment variable checks")
def validate(pipeline: str, verbose: bool, skip_env: bool):
    """Validate a pipeline file without running it."""
    
    pipeline_path = Path(pipeline)
    
    # Add backend to path
    backend_path = Path(__file__).parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    
    from pipeline.validation import validate_all, print_validation_result
    
    result, spec = validate_all(pipeline_path, check_env=not skip_env)
    
    print_validation_result(result, verbose=verbose)
    
    if not result.valid:
        sys.exit(1)
    
    if spec:
        console.print()
        
        # Show summary
        table = Table(title="Pipeline Summary")
        table.add_column("Property", style="cyan")
        table.add_column("Value")
        
        table.add_row("Name", spec.name)
        table.add_row("Version", spec.version)
        table.add_row("Types", str(len(spec.types)))
        table.add_row("Steps", str(len(spec.steps)))
        
        if spec.assets:
            if spec.assets.items:
                table.add_row("Assets", f"{len(spec.assets.items)} items")
            elif spec.assets.from_file:
                table.add_row("Assets", f"from file: {spec.assets.from_file}")
            elif spec.assets.count:
                table.add_row("Assets", f"{spec.assets.count} (generated)")
        
        console.print(table)


@cli.command()
@click.argument("pipeline", type=click.Path(exists=True))
@click.option("--graph", "-g", is_flag=True, help="Show dependency graph")
def show(pipeline: str, graph: bool):
    """Show pipeline structure and information."""
    
    pipeline_path = Path(pipeline)
    
    # Add backend to path
    backend_path = Path(__file__).parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    
    from pipeline.spec_parser import load_pipeline, visualize_dag, format_type_def
    
    spec = load_pipeline(pipeline_path)
    
    # Header
    console.print()
    console.print(Panel(
        f"[bold]{spec.name}[/bold]\n\n"
        f"{spec.description}" if spec.description else f"[bold]{spec.name}[/bold]",
        title="Pipeline",
        border_style="blue"
    ))
    
    # Types
    if spec.types:
        console.print("\n[bold]Types:[/bold]")
        for type_def in spec.types.values():
            console.print(format_type_def(type_def))
    
    # Assets
    if spec.assets:
        console.print("\n[bold]Assets:[/bold]")
        console.print(f"  Type: {spec.assets.type}")
        if spec.assets.from_file:
            console.print(f"  Source: {spec.assets.from_file}")
        elif spec.assets.items:
            console.print(f"  Count: {len(spec.assets.items)} items")
    
    # Context
    if spec.context:
        console.print("\n[bold]Context:[/bold]")
        for key, value in spec.context.items():
            display_value = str(value)[:60] + "..." if len(str(value)) > 60 else str(value)
            console.print(f"  {key}: {display_value}")
    
    # Steps
    console.print("\n[bold]Steps:[/bold]")
    
    if graph:
        # Show as DAG
        console.print(visualize_dag(spec))
    else:
        # Show as list
        for step in spec.steps:
            flags = []
            if step.for_each:
                flags.append(f"per {step.for_each}")
            if step.gather:
                flags.append("gather")
            if step.condition:
                flags.append(f"when: {step.condition[:30]}")
            
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            console.print(f"  • {step.id} ({step.type.value}){flag_str}")


@cli.command()
@click.argument("pipeline", type=click.Path(exists=True))
@click.option("--step", "-s", help="Clear specific step only")
@click.option("--asset", "-a", help="Clear specific asset only")
@click.option("--force", "-f", is_flag=True, help="Don't ask for confirmation")
def clean(pipeline: str, step: str | None, asset: str | None, force: bool):
    """Clear cached data for a pipeline.

    \b
    Use before `artgen run` to selectively re-run parts of a pipeline:
      artgen clean pipeline.yaml                    # clear everything
      artgen clean pipeline.yaml -s art_prompt      # clear one step
      artgen clean pipeline.yaml -s card_art -a elf # clear one asset in one step
    """
    
    pipeline_path = Path(pipeline)
    
    # Add backend to path
    backend_path = Path(__file__).parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    
    from pipeline.spec_parser import load_pipeline
    from pipeline.cache import CacheManager
    
    spec = load_pipeline(pipeline_path)
    
    base_path = pipeline_path.parent
    state_dir = base_path / spec.state.directory
    
    if not state_dir.exists():
        console.print("[yellow]No cache found[/yellow]")
        return
    
    cache = CacheManager(state_dir)
    
    # Determine what to clean
    if step and asset:
        target = f"step '{step}' for asset '{asset}'"
    elif step:
        target = f"step '{step}'"
    elif asset:
        target = f"asset '{asset}'"
    else:
        target = "all cached data"
    
    if not force:
        if not click.confirm(f"Clear {target}?"):
            console.print("Cancelled")
            return
    
    # Do the cleaning
    if step and asset:
        cache.invalidate_step(step, asset)
    elif step:
        # Clear all assets for this step
        cache.invalidate_step(step)
        # Also clear per-asset caches
        for s_asset in spec.assets.items if spec.assets and spec.assets.items else []:
            cache.invalidate_step(step, s_asset.get("id"))
    elif asset:
        # Clear all steps for this asset
        for s in spec.steps:
            cache.invalidate_step(s.id, asset)
    else:
        cache.invalidate_all()
        # Also remove the state directory contents
        import shutil
        for item in state_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    
    console.print(f"[green]✓[/green] Cleared {target}")


@cli.command("list")
@click.option("--dir", "-d", "directory", type=click.Path(exists=True), default=".",
              help="Directory to search")
def list_pipelines(directory: str):
    """List pipeline files in a directory."""
    
    dir_path = Path(directory)
    
    # Find pipeline files
    patterns = ["*.yaml", "*.yml", "artgen.yaml", "artgen.yml", "pipeline.yaml"]
    files = []
    
    for pattern in patterns:
        files.extend(dir_path.glob(pattern))
    
    # Deduplicate and filter
    seen = set()
    pipelines = []
    
    for f in files:
        if f.name in seen:
            continue
        seen.add(f.name)
        
        # Quick check if it's a valid pipeline
        try:
            content = f.read_text()
            if "name:" in content and "steps:" in content:
                pipelines.append(f)
        except Exception:
            pass
    
    if not pipelines:
        console.print("[yellow]No pipeline files found[/yellow]")
        return
    
    console.print(f"\n[bold]Pipeline files in {dir_path}:[/bold]\n")
    
    for p in sorted(pipelines):
        console.print(f"  • {p.name}")


def show_pipeline_plan(pipeline_path: Path):
    """Show execution plan without running."""
    
    # Add backend to path
    backend_path = Path(__file__).parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    
    from pipeline.spec_parser import load_pipeline, get_execution_order
    from pipeline.asset_loader import load_assets
    
    spec = load_pipeline(pipeline_path)
    assets = load_assets(spec, pipeline_path.parent)
    tiers = get_execution_order(spec)
    
    console.print()
    console.print(Panel(
        f"[bold]Execution Plan[/bold]\n\n"
        f"Pipeline: {spec.name}\n"
        f"Assets: {len(assets)}",
        border_style="yellow"
    ))
    
    for tier_idx, tier in enumerate(tiers):
        console.print(f"\n[bold]Tier {tier_idx}[/bold]")
        
        for step_id in tier:
            step = spec.step_index[step_id]
            
            if step.for_each == "asset":
                console.print(f"  {step_id} ({step.type.value}) × {len(assets)} assets")
            else:
                console.print(f"  {step_id} ({step.type.value})")


def _detect_missing_assets(pipeline_path: Path) -> set[str]:
    """
    Read the output manifest and return asset IDs whose output files are missing.

    Returns an empty set if no manifest exists or all files are present.
    """
    from pipeline.spec_parser import load_pipeline

    spec = load_pipeline(pipeline_path)
    base_path = pipeline_path.parent
    state_dir = base_path / spec.state.directory
    manifest_path = state_dir / "output_manifest.json"

    if not manifest_path.exists():
        console.print("[dim]No output manifest found — run the pipeline once first[/dim]")
        return set()

    with open(manifest_path) as f:
        manifest = json.load(f)

    output_dir = base_path / manifest["output_directory"]
    missing: set[str] = set()

    for rel_path, entry in manifest.get("files", {}).items():
        asset_id = entry.get("asset_id")
        if not asset_id:
            continue
        full_path = output_dir / rel_path
        if not full_path.exists():
            missing.add(asset_id)

    return missing


def _invalidate_missing_assets(
    pipeline_path: Path,
    missing_assets: set[str],
    auto_approve: bool,
) -> None:
    """
    Invalidate all caches for the given asset IDs plus any downstream global steps.
    """
    from pipeline.spec_parser import load_pipeline, get_downstream_steps
    from pipeline.cache import CacheManager

    spec = load_pipeline(pipeline_path)
    base_path = pipeline_path.parent
    state_dir = base_path / spec.state.directory
    cache = CacheManager(state_dir)

    # Find all per-asset step IDs (steps that use for_each)
    per_asset_step_ids = {s.id for s in spec.steps if s.for_each}

    # Find global steps that are downstream of any per-asset step.
    # These need to be re-run because their inputs are being regenerated.
    global_steps_to_invalidate: set[str] = set()
    for step in spec.steps:
        if step.for_each:
            continue
        # A global step depends on per-asset results if any of its requires
        # (transitively) includes a per-asset step.
        for req in step.requires:
            if req in per_asset_step_ids:
                global_steps_to_invalidate.add(step.id)
                break

    # Also add any global step downstream of those we already found
    all_global_downstream: set[str] = set()
    for gid in global_steps_to_invalidate:
        all_global_downstream |= get_downstream_steps(spec, gid)
    global_steps_to_invalidate |= {
        sid for sid in all_global_downstream
        if not any(s.for_each for s in spec.steps if s.id == sid)
    }

    # Preview
    sorted_assets = sorted(missing_assets)
    console.print(f"\n[yellow]Missing {len(missing_assets)} asset(s):[/yellow] {', '.join(sorted_assets)}")
    if global_steps_to_invalidate:
        console.print(f"[dim]Global steps to re-run: {', '.join(sorted(global_steps_to_invalidate))}[/dim]")

    if not auto_approve:
        if not click.confirm("Invalidate caches and regenerate these assets?"):
            console.print("Cancelled")
            sys.exit(0)

    # Invalidate per-asset caches
    total_invalidated = 0
    for asset_id in missing_assets:
        total_invalidated += cache.invalidate_asset(asset_id)

    # Invalidate global steps that depend on per-asset outputs
    if global_steps_to_invalidate:
        total_invalidated += cache.invalidate_global_steps(global_steps_to_invalidate)

    console.print(
        f"[yellow]Invalidated {total_invalidated} cache entries for "
        f"{len(missing_assets)} asset(s)[/yellow]"
    )


if __name__ == "__main__":
    cli()
