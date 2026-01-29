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
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="artgen")
def cli():
    """ArtGen - AI Art Generation Pipeline Runner"""
    pass


@cli.command()
@click.argument("pipeline", type=click.Path(exists=True))
@click.option("--input", "-i", "input_file", type=click.Path(exists=True),
              help="Override asset input file")
@click.option("--auto-approve", "-y", is_flag=True,
              help="Auto-approve all selections (no human interaction)")
@click.option("--verbose", "-v", is_flag=True,
              help="Show detailed output")
@click.option("--dry-run", is_flag=True,
              help="Show what would be executed without running")
def run(pipeline: str, input_file: str | None, auto_approve: bool, verbose: bool, dry_run: bool):
    """Run an ArtGen pipeline."""
    
    pipeline_path = Path(pipeline)
    
    if dry_run:
        # Just show the plan
        show_pipeline_plan(pipeline_path)
        return
    
    console.print()
    console.print(Panel(
        f"[bold]ArtGen Pipeline Runner[/bold]\n\n"
        f"Pipeline: {pipeline_path.name}\n"
        f"Auto-approve: {'Yes' if auto_approve else 'No'}",
        border_style="blue"
    ))
    console.print()
    
    # Add backend to path
    backend_path = Path(__file__).parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    
    from pipeline.executor import run_pipeline
    
    result = asyncio.run(run_pipeline(
        pipeline_path=pipeline_path,
        input_override=input_file,
        auto_approve=auto_approve,
        verbose=verbose,
    ))
    
    if not result.success:
        console.print("\n[red]Pipeline failed:[/red]")
        for error in result.errors:
            console.print(f"  • {error}")
        sys.exit(1)


@cli.command()
@click.argument("pipeline", type=click.Path(exists=True))
def validate(pipeline: str):
    """Validate a pipeline file without running it."""
    
    pipeline_path = Path(pipeline)
    
    # Add backend to path
    backend_path = Path(__file__).parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    
    from pipeline.spec_parser import load_pipeline, ParseError, ValidationError
    
    try:
        spec = load_pipeline(pipeline_path)
        
        console.print(f"[green]✓[/green] Pipeline '{spec.name}' is valid")
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
        
    except (ParseError, ValidationError) as e:
        console.print(f"[red]✗[/red] Validation failed: {e}")
        sys.exit(1)


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
    """Clear cached data for a pipeline."""
    
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


if __name__ == "__main__":
    cli()
