#!/usr/bin/env python3
"""AI Art Generator CLI.

Usage:
    artgen birds.txt                    Generate one image per line
    artgen birds.txt --style "pixel art"  With style
    artgen birds.txt --transparent      Transparent backgrounds
    artgen interactive                  Start browser-based UI
    artgen init                         Initialize new project
    artgen status                       Show project status
"""

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

# Rich for pretty output
try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.panel import Panel
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


def print_styled(message: str, style: str = ""):
    """Print with optional rich styling."""
    if console and style:
        console.print(message, style=style)
    else:
        print(message)


def print_header():
    """Print the artgen header."""
    if console:
        console.print("\n  [bold cyan]AI Art Generator[/bold cyan]\n")
    else:
        print("\n  AI Art Generator\n")


def print_error(message: str):
    """Print an error message."""
    if console:
        console.print(f"  [red]Error:[/red] {message}")
    else:
        print(f"  Error: {message}")


def print_success(message: str):
    """Print a success message."""
    if console:
        console.print(f"  [green]✓[/green] {message}")
    else:
        print(f"  ✓ {message}")


def print_info(message: str):
    """Print an info message."""
    if console:
        console.print(f"  [dim]{message}[/dim]")
    else:
        print(f"  {message}")


def setup_env(env_path: Optional[str] = None):
    """Set up environment from .env file.
    
    Search order:
    1. Explicit --env flag
    2. ARTGEN_ENV_FILE environment variable
    3. .env.local in current directory
    4. .env in current directory
    5. ~/.config/artgen/.env
    6. ~/.env.local
    """
    if env_path:
        if Path(env_path).exists():
            os.environ["ARTGEN_ENV_FILE"] = env_path
            return env_path
        else:
            print_error(f"Env file not found: {env_path}")
            sys.exit(1)
    
    # Check ARTGEN_ENV_FILE
    if os.environ.get("ARTGEN_ENV_FILE"):
        return os.environ["ARTGEN_ENV_FILE"]
    
    # Search order
    search_paths = [
        Path.cwd() / ".env.local",
        Path.cwd() / ".env",
        Path.home() / ".config" / "artgen" / ".env",
        Path.home() / ".env.local",
    ]
    
    for path in search_paths:
        if path.exists():
            os.environ["ARTGEN_ENV_FILE"] = str(path)
            return str(path)
    
    return None


def cmd_generate(args):
    """Generate images from a content file using the full pipeline."""
    print_header()
    
    # Validate input file
    input_file = Path(args.file)
    if not input_file.exists():
        print_error(f"File not found: {input_file}")
        return 1
    
    # Setup environment
    env_file = setup_env(args.env)
    if env_file:
        print_success(f"Using env: {env_file}")
    
    # Add backend to path for imports
    backend_dir = Path(__file__).parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    
    from parsers import parse_input_file
    from app.config import reload_config, get_config
    from app.models import StyleConfig, ProjectConfig, PipelineStep, StepType
    from pipeline import Project, PipelineOrchestrator
    
    # Reload config with env file
    if env_file:
        reload_config(env_file)
    
    # Check API key is configured
    config = get_config()
    if not config.providers.google_api_key:
        print_error("No API key configured!")
        print_info("Set GOOGLE_API_KEY in your environment or .env file")
        return 1
    
    # Parse input file
    items = parse_input_file(input_file)
    print_success(f"Loaded {len(items)} items from {input_file.name}")
    
    if not items:
        print_error("No items found in input file")
        return 1
    
    # Set up output directory
    output_dir = Path(args.output).absolute()
    output_dir.mkdir(parents=True, exist_ok=True)
    print_success(f"Output: {output_dir}")
    
    # Build style config from CLI args
    style = StyleConfig(
        global_prompt_prefix=args.style or "",
        aspect_ratio="1:1",
    )
    
    # Determine step type based on --transparent flag
    if args.transparent:
        step_type = StepType.GENERATE_SPRITE
        step_id = "generate_sprite"
    else:
        step_type = StepType.GENERATE_IMAGE
        step_id = "generate_image"
    
    # Build pipeline config
    pipeline = [
        PipelineStep(
            id=step_id,
            type=step_type,
            variations=args.variations,
            requires_approval=False,  # CLI mode = auto-approve
            config={"auto_remove_background": args.transparent},
        ),
    ]
    
    # Create project config for this run
    project_config = ProjectConfig(
        name=f"CLI: {input_file.name}",
        style=style,
        pipeline=pipeline,
        default_image_provider=args.provider,
    )
    
    # Run generation
    async def generate_all():
        # Initialize project in output directory
        project = Project(output_dir, project_config)
        project.ensure_directories()
        await project.save_config()
        
        orchestrator = PipelineOrchestrator(project)
        
        total = len(items)
        successful = 0
        failed = 0
        failed_items = []
        
        if console:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TextColumn("[dim]{task.fields[status]}[/dim]"),
                console=console,
            ) as progress:
                task = progress.add_task(
                    "Generating...", 
                    total=total,
                    status=""
                )
                
                for i, item in enumerate(items):
                    # Truncate description for display
                    desc = item.description[:40] + "..." if len(item.description) > 40 else item.description
                    progress.update(task, description=f"[cyan]{desc}[/cyan]", status=f"{i+1}/{total}")
                    
                    try:
                        # Create asset
                        asset = await project.create_asset(item)
                        
                        # Process through pipeline (auto_approve=True for CLI)
                        result = await orchestrator.process_asset(asset, auto_approve=True)
                        
                        if result.status.value == "completed":
                            successful += 1
                            # Show what was generated
                            if args.verbose:
                                for step_id, step_result in result.results.items():
                                    if step_result.variations:
                                        for v in step_result.variations:
                                            if v.path:
                                                console.print(f"    [dim]→ {v.path}[/dim]")
                        else:
                            failed += 1
                            failed_items.append((item, f"Status: {result.status.value}"))
                            if args.verbose:
                                # Show error if available
                                for step_id, step_result in result.results.items():
                                    if step_result.error:
                                        console.print(f"    [red]Error:[/red] {step_result.error}")
                        
                    except Exception as e:
                        failed += 1
                        failed_items.append((item, str(e)))
                        if args.verbose:
                            console.print(f"    [red]Error:[/red] {e}")
                    
                    progress.update(task, advance=1)
        else:
            # Non-rich fallback
            for i, item in enumerate(items):
                desc = item.description[:50] + "..." if len(item.description) > 50 else item.description
                print(f"  [{i+1}/{total}] {desc}")
                
                try:
                    asset = await project.create_asset(item)
                    result = await orchestrator.process_asset(asset, auto_approve=True)
                    
                    if result.status.value == "completed":
                        successful += 1
                        print(f"       ✓ Saved to {asset.id}/")
                    else:
                        failed += 1
                        failed_items.append((item, f"Status: {result.status.value}"))
                        print(f"       ✗ {result.status.value}")
                        
                except Exception as e:
                    failed += 1
                    failed_items.append((item, str(e)))
                    print(f"       ✗ Failed: {e}")
        
        return successful, failed, failed_items
    
    successful, failed, failed_items = asyncio.run(generate_all())
    
    # Summary
    print()
    total_images = successful * args.variations
    if successful > 0:
        print_success(f"Done! {successful} items → {total_images} images generated")
    
    if failed > 0:
        print_error(f"{failed} items failed")
        if args.verbose and failed_items:
            for item, error in failed_items[:5]:  # Show first 5 errors
                print_info(f"  • {item.id}: {error[:60]}")
            if len(failed_items) > 5:
                print_info(f"  ... and {len(failed_items) - 5} more")
    
    print_info(f"Output: {output_dir}")
    
    return 0 if failed == 0 else 1


def find_available_port(start_port: int, max_attempts: int = 20) -> int:
    """Find an available port starting from start_port."""
    import socket
    
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    
    raise RuntimeError(f"Could not find available port in range {start_port}-{start_port + max_attempts}")


def is_port_available(port: int) -> bool:
    """Check if a port is available."""
    import socket
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def wait_for_port(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
    """Wait for a port to start accepting connections."""
    import socket
    import time
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect(("127.0.0.1", port))
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(interval)
    return False


def cmd_interactive(args):
    """Start the interactive browser-based UI."""
    import time
    
    print_header()
    
    # Setup environment
    env_file = setup_env(args.env)
    if env_file:
        print_success(f"Using env: {env_file}")
    
    # Add backend to path
    backend_dir = Path(__file__).parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    
    # Find frontend directory
    frontend_dir = backend_dir.parent / "frontend"
    if not frontend_dir.exists():
        print_error(f"Frontend not found at {frontend_dir}")
        print_info("Make sure you have the full artgen installation")
        return 1
    
    # Check if node_modules exists
    if not (frontend_dir / "node_modules").exists():
        print_info("Installing frontend dependencies...")
        result = subprocess.run(
            ["npm", "install"],
            cwd=frontend_dir,
            capture_output=True,
        )
        if result.returncode != 0:
            print_error("Failed to install frontend dependencies")
            print_info("Run: cd frontend && npm install")
            return 1
        print_success("Frontend dependencies installed")
    
    # Smart port management
    backend_port = args.port
    frontend_port = args.ui_port
    
    # Check and find available ports
    if not is_port_available(backend_port):
        old_port = backend_port
        backend_port = find_available_port(backend_port)
        print_info(f"Port {old_port} in use, using {backend_port} for backend")
    
    if not is_port_available(frontend_port):
        old_port = frontend_port
        frontend_port = find_available_port(frontend_port)
        print_info(f"Port {old_port} in use, using {frontend_port} for frontend")
    
    print_info("Starting services...")
    
    # Track child processes for cleanup
    processes = []
    shutdown_in_progress = False
    
    def cleanup(signum=None, frame=None):
        """Clean up child processes."""
        nonlocal shutdown_in_progress
        if shutdown_in_progress:
            return
        shutdown_in_progress = True
        
        print()
        print_info("Shutting down...")
        for name, proc in processes:
            if proc.poll() is None:  # Still running
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                print_success(f"{name} stopped")
        print()
        print_info("Goodbye!")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    
    # Start backend
    backend_env = os.environ.copy()
    if env_file:
        backend_env["ARTGEN_ENV_FILE"] = env_file
    
    backend_proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", str(backend_port),
        ],
        cwd=backend_dir,
        env=backend_env,
        stdout=subprocess.PIPE if not args.verbose else None,
        stderr=subprocess.PIPE if not args.verbose else None,
    )
    processes.append(("Backend", backend_proc))
    
    # Wait for backend to be ready
    if not wait_for_port(backend_port, timeout=15.0):
        if backend_proc.poll() is not None:
            # Process died, get error output
            if not args.verbose:
                _, stderr = backend_proc.communicate()
                if stderr:
                    print_error(f"Backend failed: {stderr.decode()[:200]}")
            print_error("Backend failed to start")
        else:
            print_error("Backend did not become ready in time")
        cleanup()
        return 1
    
    print_success(f"Backend API     http://localhost:{backend_port}")
    
    # Start frontend with strict port (no auto-switching)
    frontend_env = os.environ.copy()
    frontend_env["VITE_API_URL"] = f"http://localhost:{backend_port}"
    
    frontend_proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(frontend_port), "--strictPort"],
        cwd=frontend_dir,
        env=frontend_env,
        stdout=subprocess.PIPE if not args.verbose else None,
        stderr=subprocess.PIPE if not args.verbose else None,
    )
    processes.append(("Frontend", frontend_proc))
    
    # Wait for frontend to be ready
    if not wait_for_port(frontend_port, timeout=30.0):
        if frontend_proc.poll() is not None:
            print_error("Frontend failed to start")
        else:
            print_error("Frontend did not become ready in time")
        cleanup()
        return 1
    
    print_success(f"Frontend UI     http://localhost:{frontend_port}")
    
    # Load content file if provided
    if args.file:
        input_file = Path(args.file)
        if input_file.exists():
            # POST to the backend to load the file
            try:
                import httpx
                with open(input_file, "r") as f:
                    content = f.read()
                
                # Detect format from extension
                suffix = input_file.suffix.lower()
                fmt = "text"
                if suffix == ".json":
                    fmt = "json"
                elif suffix == ".jsonl":
                    fmt = "jsonl"
                elif suffix == ".csv":
                    fmt = "csv"
                elif suffix == ".tsv":
                    fmt = "tsv"
                
                response = httpx.post(
                    f"http://localhost:{backend_port}/assets/upload",
                    json={"content": content, "format": fmt},
                    timeout=30.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    count = len(data.get("assets", []))
                    print_success(f"Loaded {count} items from {input_file.name}")
                else:
                    print_error(f"Failed to load {input_file.name}")
            except Exception as e:
                print_error(f"Failed to load content: {e}")
        else:
            print_error(f"File not found: {args.file}")
    
    # Open browser
    if not args.no_browser:
        print_success("Opening browser...")
        webbrowser.open(f"http://localhost:{frontend_port}")
    
    print()
    if console:
        console.print(Panel(
            "[bold]Ready![/bold] Use the browser to upload content and approve generations.\n\n"
            "Press [bold cyan]Ctrl+C[/bold cyan] to stop all services.",
            border_style="green",
        ))
    else:
        print("  Ready! Use the browser to upload content and approve generations.")
        print("  Press Ctrl+C to stop all services.")
    print()
    
    # Wait for processes
    try:
        while True:
            # Check if either process has died
            if backend_proc.poll() is not None:
                print_error("Backend stopped unexpectedly")
                cleanup()
                return 1
            if frontend_proc.poll() is not None:
                print_error("Frontend stopped unexpectedly")
                cleanup()
                return 1
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()
    
    return 0


def cmd_init(args):
    """Initialize a new project."""
    print_header()
    
    # Setup environment
    env_file = setup_env(args.env)
    
    # Add backend to path
    backend_dir = Path(__file__).parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    
    from pipeline import Project
    
    async def init():
        if Project.exists():
            print_error("Project already exists (artgen.json found)")
            return 1
        
        project = await Project.init()
        print_success(f"Created artgen.json")
        print_success(f"Created outputs/ directory")
        
        print()
        print_info("Next steps:")
        print_info("  1. Set up API keys in .env.local or export GOOGLE_API_KEY")
        print_info("  2. Create a content file (birds.txt, cards.csv, etc.)")
        print_info("  3. Run: artgen your-content.txt")
        print_info("     Or:  artgen interactive")
        
        return 0
    
    return asyncio.run(init())


def cmd_status(args):
    """Show project status."""
    print_header()
    
    # Setup environment
    env_file = setup_env(args.env)
    
    # Add backend to path
    backend_dir = Path(__file__).parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    
    from pipeline import Project
    from app.config import reload_config, get_config
    
    if env_file:
        reload_config(env_file)
    
    async def status():
        config = get_config()
        
        if not Project.exists():
            print_info("No project in current directory")
            print_info("Run 'artgen init' to create one, or 'artgen <file>' to generate directly")
            print()
        else:
            project = await Project.load()
            
            if console:
                table = Table(show_header=False, box=None, padding=(0, 2))
                table.add_column(style="bold")
                table.add_column()
                table.add_row("Project:", project.config.name)
                table.add_row("Location:", str(project.path))
                table.add_row("Assets:", str(len(project._assets)))
                
                if project.config.pipeline:
                    pipeline_str = " → ".join(s.type.value if hasattr(s.type, 'value') else str(s.type) for s in project.config.pipeline)
                    table.add_row("Pipeline:", pipeline_str)
                
                console.print(table)
            else:
                print(f"  Project:  {project.config.name}")
                print(f"  Location: {project.path}")
                print(f"  Assets:   {len(project._assets)}")
            
            print()
        
        # Show API key status
        if console:
            console.print("  [bold]API Keys:[/bold]")
        else:
            print("  API Keys:")
        
        keys = [
            ("Google/Gemini", bool(config.providers.google_api_key)),
            ("OpenAI", bool(config.providers.openai_api_key)),
            ("Anthropic", bool(config.providers.anthropic_api_key)),
            ("Tavily", bool(config.providers.tavily_api_key)),
        ]
        
        for name, configured in keys:
            if configured:
                print_success(f"{name} configured")
            else:
                if console:
                    console.print(f"  [dim]✗ {name} not configured[/dim]")
                else:
                    print(f"  ✗ {name} not configured")
        
        if env_file:
            print()
            print_info(f"Env file: {env_file}")
        
        return 0
    
    return asyncio.run(status())


def cmd_list(args):
    """List assets in the current project."""
    print_header()
    
    # Setup environment
    env_file = setup_env(args.env)
    
    # Add backend to path
    backend_dir = Path(__file__).parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    
    from pipeline import Project
    from app.models import AssetStatus
    
    async def list_assets():
        if not Project.exists():
            print_info("No project in current directory")
            print_info("Run 'artgen init' to create one")
            return 0
        
        project = await Project.load()
        assets = list(project._assets.values())
        
        if not assets:
            print_info("No assets in project yet")
            print_info("Run 'artgen <file>' to generate some")
            return 0
        
        # Filter by status if requested
        if args.status:
            try:
                status_filter = AssetStatus(args.status)
                assets = [a for a in assets if a.status == status_filter]
            except ValueError:
                print_error(f"Unknown status: {args.status}")
                print_info(f"Valid statuses: {', '.join(s.value for s in AssetStatus)}")
                return 1
        
        # Sort by updated_at
        assets.sort(key=lambda a: a.updated_at or a.created_at, reverse=True)
        
        # Limit if requested
        if args.limit:
            assets = assets[:args.limit]
        
        if console:
            from rich.table import Table
            
            table = Table(show_header=True, header_style="bold")
            table.add_column("ID", style="cyan")
            table.add_column("Status", style="dim")
            table.add_column("Step")
            table.add_column("Description")
            
            for asset in assets:
                # Determine status style
                status = asset.status.value
                if asset.status == AssetStatus.COMPLETED:
                    status_str = f"[green]{status}[/green]"
                elif asset.status == AssetStatus.FAILED:
                    status_str = f"[red]{status}[/red]"
                elif asset.status == AssetStatus.PROCESSING:
                    status_str = f"[yellow]{status}[/yellow]"
                elif asset.status == AssetStatus.AWAITING_APPROVAL:
                    status_str = f"[blue]{status}[/blue]"
                else:
                    status_str = status
                
                # Truncate description
                desc = asset.input_description
                if len(desc) > 40:
                    desc = desc[:37] + "..."
                
                # Current step
                step = asset.current_step or "-"
                
                table.add_row(asset.id, status_str, step, desc)
            
            console.print(table)
            
            # Summary
            print()
            total = len(project._assets)
            completed = sum(1 for a in project._assets.values() if a.status == AssetStatus.COMPLETED)
            failed = sum(1 for a in project._assets.values() if a.status == AssetStatus.FAILED)
            pending = sum(1 for a in project._assets.values() if a.status == AssetStatus.PENDING)
            
            console.print(f"  Total: {total}  [green]Completed: {completed}[/green]  [red]Failed: {failed}[/red]  Pending: {pending}")
        else:
            # Non-rich fallback
            print(f"{'ID':<12} {'Status':<12} {'Step':<20} Description")
            print("-" * 70)
            for asset in assets:
                desc = asset.input_description[:35] + "..." if len(asset.input_description) > 35 else asset.input_description
                step = asset.current_step or "-"
                print(f"{asset.id:<12} {asset.status.value:<12} {step:<20} {desc}")
        
        return 0
    
    return asyncio.run(list_assets())


def cmd_show(args):
    """Show details of a specific asset."""
    print_header()
    
    # Setup environment
    env_file = setup_env(args.env)
    
    # Add backend to path
    backend_dir = Path(__file__).parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    
    from pipeline import Project
    
    async def show_asset():
        if not Project.exists():
            print_error("No project in current directory")
            return 1
        
        project = await Project.load()
        asset = project.get_asset(args.asset_id)
        
        if not asset:
            print_error(f"Asset not found: {args.asset_id}")
            print_info(f"Run 'artgen list' to see all assets")
            return 1
        
        if console:
            from rich.panel import Panel
            from rich.table import Table
            
            # Asset header
            console.print(Panel(
                f"[bold]{asset.id}[/bold]\n{asset.input_description}",
                title="Asset Details",
                border_style="cyan",
            ))
            
            # Status and metadata
            status_color = {
                "completed": "green",
                "failed": "red",
                "processing": "yellow",
                "pending": "dim",
                "awaiting_approval": "blue",
            }.get(asset.status.value, "white")
            
            console.print(f"\n  Status: [{status_color}]{asset.status.value}[/{status_color}]")
            if asset.current_step:
                console.print(f"  Current Step: {asset.current_step}")
            console.print(f"  Created: {asset.created_at}")
            
            # Results table
            if asset.results:
                print()
                table = Table(show_header=True, header_style="bold")
                table.add_column("Step")
                table.add_column("Status")
                table.add_column("Variations")
                table.add_column("Output")
                
                for step_id, result in asset.results.items():
                    status = result.status.value
                    num_vars = len(result.variations) if result.variations else 0
                    
                    # Get first output path
                    output = "-"
                    if result.variations:
                        v = result.variations[0]
                        if v.path:
                            output = v.path
                        elif v.content:
                            output = v.content[:30] + "..."
                    
                    table.add_row(step_id, status, str(num_vars), output)
                
                console.print(table)
            
            # Show output directory
            asset_dir = project.get_asset_dir(asset.id)
            if asset_dir.exists():
                files = list(asset_dir.glob("*"))
                if files:
                    print()
                    console.print(f"  [dim]Output directory: {asset_dir}[/dim]")
                    for f in files[:5]:
                        console.print(f"    → {f.name}")
                    if len(files) > 5:
                        console.print(f"    [dim]... and {len(files) - 5} more files[/dim]")
        else:
            # Non-rich fallback
            print(f"Asset: {asset.id}")
            print(f"Description: {asset.input_description}")
            print(f"Status: {asset.status.value}")
            if asset.current_step:
                print(f"Current Step: {asset.current_step}")
            
            if asset.results:
                print("\nResults:")
                for step_id, result in asset.results.items():
                    print(f"  {step_id}: {result.status.value}")
        
        return 0
    
    return asyncio.run(show_asset())


def cmd_run(args):
    """Run a specific pipeline step on input files.
    
    This allows running individual steps for testing or partial processing:
    - artgen run generate_image birds.txt
    - artgen run remove_background --project ./my-project
    """
    print_header()
    
    # Validate step type
    valid_steps = ["generate_image", "generate_sprite", "generate_name", "generate_text", "research", "remove_background"]
    if args.step not in valid_steps:
        print_error(f"Unknown step: {args.step}")
        print_info(f"Valid steps: {', '.join(valid_steps)}")
        return 1
    
    # Setup environment
    env_file = setup_env(args.env)
    if env_file:
        print_success(f"Using env: {env_file}")
    
    # Add backend to path for imports
    backend_dir = Path(__file__).parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    
    from app.config import reload_config, get_config
    from app.models import AssetStatus, PipelineStep, StepType
    from pipeline import Project, PipelineOrchestrator
    
    if env_file:
        reload_config(env_file)
    
    # Check API key
    config = get_config()
    if not config.providers.google_api_key:
        print_error("No API key configured!")
        print_info("Set GOOGLE_API_KEY in your environment or .env file")
        return 1
    
    async def run_step():
        # Map step name to StepType
        step_type_map = {
            "generate_image": StepType.GENERATE_IMAGE,
            "generate_sprite": StepType.GENERATE_SPRITE,
            "generate_name": StepType.GENERATE_NAME,
            "generate_text": StepType.GENERATE_TEXT,
            "research": StepType.RESEARCH,
            "remove_background": StepType.REMOVE_BACKGROUND,
        }
        step_type = step_type_map[args.step]
        
        # Mode 1: Run on existing project assets
        if not args.input:
            if not Project.exists():
                print_error("No project in current directory and no input file specified")
                print_info("Either run 'artgen init' or provide --input <file>")
                return 1
            
            project = await Project.load()
            
            # Override project pipeline with just the single step we want to run
            project.config.pipeline = [
                PipelineStep(
                    id=args.step,
                    type=step_type,
                    variations=args.variations,
                    requires_approval=False,
                    config={},
                ),
            ]
            
            # Get assets to process
            if args.asset_id:
                asset = project.get_asset(args.asset_id)
                if not asset:
                    print_error(f"Asset not found: {args.asset_id}")
                    return 1
                assets_to_process = [asset]
            else:
                # Process all pending/failed assets
                assets_to_process = [
                    a for a in project._assets.values()
                    if a.status in (AssetStatus.PENDING, AssetStatus.FAILED)
                ]
            
            if not assets_to_process:
                print_info("No assets to process")
                return 0
            
            print_success(f"Found {len(assets_to_process)} assets to process with step: {args.step}")
            
        # Mode 2: Run on input file (creates temporary project)
        else:
            input_file = Path(args.input)
            if not input_file.exists():
                print_error(f"File not found: {input_file}")
                return 1
            
            from parsers import parse_input_file
            from app.models import StyleConfig, ProjectConfig
            
            items = parse_input_file(input_file)
            print_success(f"Loaded {len(items)} items from {input_file.name}")
            
            if not items:
                print_error("No items found in input file")
                return 1
            
            # Set up output directory
            output_dir = Path(args.output).absolute()
            output_dir.mkdir(parents=True, exist_ok=True)
            print_success(f"Output: {output_dir}")
            
            # Build single-step pipeline
            pipeline = [
                PipelineStep(
                    id=args.step,
                    type=step_type,
                    variations=args.variations,
                    requires_approval=False,
                    config={},
                ),
            ]
            
            # Create project config
            project_config = ProjectConfig(
                name=f"CLI: {args.step}",
                style=StyleConfig(
                    global_prompt_prefix=args.style or "",
                    aspect_ratio="1:1",
                ),
                pipeline=pipeline,
            )
            
            # Initialize project
            project = Project(output_dir, project_config)
            project.ensure_directories()
            await project.save_config()
            
            # Create assets from items
            assets_to_process = []
            for item in items:
                asset = await project.create_asset(item)
                assets_to_process.append(asset)
        
        # Run the step on each asset
        orchestrator = PipelineOrchestrator(project)
        
        total = len(assets_to_process)
        successful = 0
        failed = 0
        failed_items = []
        
        if console:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TextColumn("[dim]{task.fields[status]}[/dim]"),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"Running {args.step}...",
                    total=total,
                    status=""
                )
                
                for i, asset in enumerate(assets_to_process):
                    desc = asset.input_description[:40] + "..." if len(asset.input_description) > 40 else asset.input_description
                    progress.update(task, description=f"[cyan]{desc}[/cyan]", status=f"{i+1}/{total}")
                    
                    try:
                        result = await orchestrator.process_asset(asset, auto_approve=True)
                        
                        if result.status == AssetStatus.COMPLETED:
                            successful += 1
                            if args.verbose:
                                for step_id, step_result in result.results.items():
                                    if step_result.variations:
                                        for v in step_result.variations:
                                            if v.path:
                                                console.print(f"    [dim]→ {v.path}[/dim]")
                                            elif v.content:
                                                console.print(f"    [dim]→ {v.content[:50]}...[/dim]")
                        else:
                            failed += 1
                            failed_items.append((asset, f"Status: {result.status.value}"))
                            
                    except Exception as e:
                        failed += 1
                        failed_items.append((asset, str(e)))
                        if args.verbose:
                            console.print(f"    [red]Error:[/red] {e}")
                    
                    progress.update(task, advance=1)
        else:
            for i, asset in enumerate(assets_to_process):
                desc = asset.input_description[:50] + "..." if len(asset.input_description) > 50 else asset.input_description
                print(f"  [{i+1}/{total}] {desc}")
                
                try:
                    result = await orchestrator.process_asset(asset, auto_approve=True)
                    
                    if result.status == AssetStatus.COMPLETED:
                        successful += 1
                        print(f"       ✓ Done")
                    else:
                        failed += 1
                        failed_items.append((asset, f"Status: {result.status.value}"))
                        print(f"       ✗ {result.status.value}")
                        
                except Exception as e:
                    failed += 1
                    failed_items.append((asset, str(e)))
                    print(f"       ✗ Failed: {e}")
        
        print()
        if successful > 0:
            print_success(f"Done! {successful} assets processed with {args.step}")
        if failed > 0:
            print_error(f"{failed} assets failed")
            if args.verbose and failed_items:
                for asset, error in failed_items[:5]:
                    print_info(f"  • {asset.id}: {error[:60]}")
        
        return 0 if failed == 0 else 1
    
    return asyncio.run(run_step())


def cmd_resume(args):
    """Resume processing of pending/failed assets."""
    print_header()
    
    # Setup environment
    env_file = setup_env(args.env)
    if env_file:
        print_success(f"Using env: {env_file}")
    
    # Add backend to path
    backend_dir = Path(__file__).parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    
    from app.config import reload_config, get_config
    from app.models import AssetStatus
    from pipeline import Project, PipelineOrchestrator
    
    if env_file:
        reload_config(env_file)
    
    # Check API key
    config = get_config()
    if not config.providers.google_api_key:
        print_error("No API key configured!")
        print_info("Set GOOGLE_API_KEY in your environment or .env file")
        return 1
    
    async def resume_processing():
        if not Project.exists():
            print_error("No project in current directory")
            print_info("Run 'artgen init' to create one")
            return 1
        
        project = await Project.load()
        
        # Get resumable assets (pending or failed)
        if args.failed_only:
            assets_to_process = [a for a in project._assets.values() if a.status == AssetStatus.FAILED]
            filter_desc = "failed"
        else:
            assets_to_process = [a for a in project._assets.values() 
                               if a.status in (AssetStatus.PENDING, AssetStatus.FAILED, AssetStatus.PROCESSING)]
            filter_desc = "pending/failed"
        
        if not assets_to_process:
            print_info(f"No {filter_desc} assets to resume")
            return 0
        
        print_success(f"Found {len(assets_to_process)} {filter_desc} assets to resume")
        
        orchestrator = PipelineOrchestrator(project)
        
        total = len(assets_to_process)
        successful = 0
        failed = 0
        failed_items = []
        
        if console:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TextColumn("[dim]{task.fields[status]}[/dim]"),
                console=console,
            ) as progress:
                task = progress.add_task(
                    "Resuming...",
                    total=total,
                    status=""
                )
                
                for i, asset in enumerate(assets_to_process):
                    desc = asset.input_description[:40] + "..." if len(asset.input_description) > 40 else asset.input_description
                    progress.update(task, description=f"[cyan]{desc}[/cyan]", status=f"{i+1}/{total}")
                    
                    try:
                        # Reset status if failed
                        if asset.status == AssetStatus.FAILED:
                            asset.status = AssetStatus.PENDING
                            # Clear failed steps to retry
                            for step_id, result in asset.results.items():
                                if result.status == AssetStatus.FAILED:
                                    result.status = AssetStatus.PENDING
                                    result.error = None
                            await project.save_asset(asset)
                        
                        result = await orchestrator.process_asset(asset, auto_approve=True)
                        
                        if result.status == AssetStatus.COMPLETED:
                            successful += 1
                            if args.verbose:
                                for step_id, step_result in result.results.items():
                                    if step_result.variations:
                                        for v in step_result.variations:
                                            if v.path:
                                                console.print(f"    [dim]→ {v.path}[/dim]")
                        else:
                            failed += 1
                            failed_items.append((asset, f"Status: {result.status.value}"))
                            
                    except Exception as e:
                        failed += 1
                        failed_items.append((asset, str(e)))
                        if args.verbose:
                            console.print(f"    [red]Error:[/red] {e}")
                    
                    progress.update(task, advance=1)
        else:
            for i, asset in enumerate(assets_to_process):
                desc = asset.input_description[:50] + "..." if len(asset.input_description) > 50 else asset.input_description
                print(f"  [{i+1}/{total}] {desc}")
                
                try:
                    if asset.status == AssetStatus.FAILED:
                        asset.status = AssetStatus.PENDING
                        for step_id, result in asset.results.items():
                            if result.status == AssetStatus.FAILED:
                                result.status = AssetStatus.PENDING
                                result.error = None
                        await project.save_asset(asset)
                    
                    result = await orchestrator.process_asset(asset, auto_approve=True)
                    
                    if result.status == AssetStatus.COMPLETED:
                        successful += 1
                        print(f"       ✓ Done")
                    else:
                        failed += 1
                        failed_items.append((asset, f"Status: {result.status.value}"))
                        print(f"       ✗ {result.status.value}")
                        
                except Exception as e:
                    failed += 1
                    failed_items.append((asset, str(e)))
                    print(f"       ✗ Failed: {e}")
        
        print()
        if successful > 0:
            print_success(f"Done! {successful} assets completed")
        if failed > 0:
            print_error(f"{failed} assets still failed")
            if args.verbose and failed_items:
                for asset, error in failed_items[:5]:
                    print_info(f"  • {asset.id}: {error[:60]}")
        
        return 0 if failed == 0 else 1
    
    return asyncio.run(resume_processing())


def main():
    """Main CLI entry point."""
    # Check if first arg looks like a file (not a known command or flag)
    known_commands = {"interactive", "init", "status", "list", "show", "resume", "run", "-h", "--help", "-v", "--verbose", "-e", "--env"}
    
    if len(sys.argv) > 1:
        first_arg = sys.argv[1]
        # If first arg isn't a known command/flag and doesn't start with -, assume it's a file
        if first_arg not in known_commands and not first_arg.startswith("-"):
            # Treat as generate command
            generate_parser = argparse.ArgumentParser(
                prog="artgen",
                description="Generate images from a content file",
                formatter_class=argparse.RawDescriptionHelpFormatter,
                epilog="""
Examples:
  artgen birds.txt                          Generate one image per line
  artgen birds.txt -n 4                     Generate 4 variations each
  artgen birds.txt --style "pixel art"      Apply style to all prompts
  artgen units.txt --transparent            Create sprites with transparency
  artgen cards.csv -n 4 -v                  Verbose output with 4 variations
                """,
            )
            generate_parser.add_argument("file", help="Input file (txt, csv, json, jsonl)")
            generate_parser.add_argument("-e", "--env", help="Path to .env file", metavar="PATH")
            generate_parser.add_argument("-o", "--output", default="./outputs", help="Output directory (default: ./outputs)")
            generate_parser.add_argument("-s", "--style", help="Style prompt to apply (e.g. 'pixel art, 16-bit')")
            generate_parser.add_argument("-t", "--transparent", action="store_true", help="Create sprites with transparent backgrounds")
            generate_parser.add_argument("-n", "--variations", type=int, default=1, help="Variations per item (default: 1)")
            generate_parser.add_argument("-p", "--provider", default="gemini", 
                                        choices=["gemini", "gemini_pro"],
                                        help="Image provider: gemini (fast) or gemini_pro (higher quality)")
            generate_parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed output")
            
            args = generate_parser.parse_args()
            return cmd_generate(args)
    
    # Standard command parsing
    parser = argparse.ArgumentParser(
        prog="artgen",
        description="AI Art Generator - Batch AI art generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  artgen birds.txt                       Generate one image per line
  artgen birds.txt --style "pixel art"   Apply style to all prompts
  artgen birds.txt --transparent         Create sprites with transparency
  artgen birds.txt -n 4                  Generate 4 variations each
  
  artgen list                            List all assets in project
  artgen show item-001                   Show details of an asset
  artgen resume                          Resume failed/pending assets
  artgen run generate_image birds.txt    Run specific pipeline step
  
  artgen interactive                     Start browser-based UI
  artgen init                            Initialize new project
  artgen status                          Show project and API status

First time? Run: artgen init
        """,
    )
    
    # Global options
    parser.add_argument(
        "-e", "--env",
        help="Path to .env file with API keys",
        metavar="PATH",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed output",
    )
    
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    
    # interactive command
    interactive_parser = subparsers.add_parser(
        "interactive",
        help="Start browser-based interactive mode",
        description="Start the browser-based UI for interactive approval workflow",
    )
    interactive_parser.add_argument(
        "file",
        nargs="?",
        help="Optional content file to pre-load",
        metavar="FILE",
    )
    interactive_parser.add_argument(
        "-e", "--env",
        help="Path to .env file",
        metavar="PATH",
    )
    interactive_parser.add_argument(
        "-p", "--port",
        type=int,
        default=8000,
        help="Backend API port (default: 8000)",
    )
    interactive_parser.add_argument(
        "-P", "--ui-port",
        type=int,
        default=5173,
        help="Frontend UI port (default: 5173)",
    )
    interactive_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open browser",
    )
    interactive_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show server logs",
    )
    interactive_parser.set_defaults(func=cmd_interactive)
    
    # init command
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize a new project",
        description="Create artgen.json and outputs/ in current directory",
    )
    init_parser.add_argument(
        "-e", "--env",
        help="Path to .env file",
        metavar="PATH",
    )
    init_parser.set_defaults(func=cmd_init)
    
    # status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show project status",
        description="Show project configuration and API key status",
    )
    status_parser.add_argument(
        "-e", "--env",
        help="Path to .env file",
        metavar="PATH",
    )
    status_parser.set_defaults(func=cmd_status)
    
    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List assets in current project",
        description="List all assets with their status",
    )
    list_parser.add_argument(
        "-e", "--env",
        help="Path to .env file",
        metavar="PATH",
    )
    list_parser.add_argument(
        "-s", "--status",
        help="Filter by status (pending, completed, failed, etc.)",
        metavar="STATUS",
    )
    list_parser.add_argument(
        "-n", "--limit",
        type=int,
        help="Limit number of results",
        metavar="N",
    )
    list_parser.set_defaults(func=cmd_list)
    
    # show command
    show_parser = subparsers.add_parser(
        "show",
        help="Show details of a specific asset",
        description="Show detailed information about an asset",
    )
    show_parser.add_argument(
        "asset_id",
        help="Asset ID to show",
    )
    show_parser.add_argument(
        "-e", "--env",
        help="Path to .env file",
        metavar="PATH",
    )
    show_parser.set_defaults(func=cmd_show)
    
    # resume command
    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume processing pending/failed assets",
        description="Continue processing assets that are pending or failed",
    )
    resume_parser.add_argument(
        "-e", "--env",
        help="Path to .env file",
        metavar="PATH",
    )
    resume_parser.add_argument(
        "-f", "--failed-only",
        action="store_true",
        help="Only retry failed assets (skip pending)",
    )
    resume_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed output",
    )
    resume_parser.set_defaults(func=cmd_resume)
    
    # run command
    run_parser = subparsers.add_parser(
        "run",
        help="Run a specific pipeline step",
        description="Run a single pipeline step on input files or existing project assets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Steps:
  generate_image      Generate images from prompts
  generate_sprite     Generate pixel art sprites with transparency
  generate_name       Generate creative names
  generate_text       Generate text descriptions
  research            Research concepts using AI
  remove_background   Remove backgrounds from existing images

Examples:
  artgen run generate_image birds.txt           Run image generation on input file
  artgen run generate_sprite units.txt -n 4     Generate 4 sprite variations each
  artgen run remove_background                  Remove backgrounds on project assets
  artgen run generate_name --asset item-001     Run on specific asset
        """,
    )
    run_parser.add_argument(
        "step",
        help="Pipeline step to run (generate_image, generate_sprite, etc.)",
        metavar="STEP",
    )
    run_parser.add_argument(
        "input",
        nargs="?",
        help="Input file (txt, csv, json, jsonl). If omitted, uses current project",
        metavar="FILE",
    )
    run_parser.add_argument(
        "-e", "--env",
        help="Path to .env file",
        metavar="PATH",
    )
    run_parser.add_argument(
        "-o", "--output",
        default="./outputs",
        help="Output directory (default: ./outputs)",
        metavar="DIR",
    )
    run_parser.add_argument(
        "-s", "--style",
        help="Style prompt to apply",
        metavar="STYLE",
    )
    run_parser.add_argument(
        "-n", "--variations",
        type=int,
        default=1,
        help="Variations to generate (default: 1)",
        metavar="N",
    )
    run_parser.add_argument(
        "-a", "--asset",
        dest="asset_id",
        help="Run on specific asset ID (for project mode)",
        metavar="ID",
    )
    run_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed output",
    )
    run_parser.set_defaults(func=cmd_run)
    
    args = parser.parse_args()
    
    # No command - show help
    if not args.command:
        parser.print_help()
        return 0
    
    # Run the command
    if hasattr(args, "func"):
        return args.func(args)
    
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
