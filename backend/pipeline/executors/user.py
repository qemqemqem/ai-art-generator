"""
User Interaction Executors.

Handles human-in-the-loop steps:
  - user_select: User chooses from K variations
  - user_approve: User approves or rejects

Supports two modes:
  - CLI mode: Terminal prompts (blocking)
  - Web mode: Browser-based approval via WebApprovalBridge
"""

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.table import Table
from rich.panel import Panel

from .base import ExecutorContext, StepExecutor, StepResult
from .registry import register_executor
from ..templates import substitute_template

console = Console()


def _get_web_bridge():
    """Get the web bridge if in web mode."""
    try:
        from ..web_bridge import get_bridge
        bridge = get_bridge()
        # Check if bridge has a broadcast callback set (indicates web mode)
        if bridge._broadcast_callback is not None:
            return bridge
    except Exception:
        pass
    return None


@register_executor("user_select")
class UserSelectExecutor(StepExecutor):
    """Execute user selection steps (CLI or web mode)."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute a user selection step.
        
        Config:
            prompt: Message to display to user
            options_from: Step ID containing variations to choose from
            allow_regenerate: Allow user to request regeneration (default: True)
        """
        import time
        start = time.time()
        
        prompt_text = config.get("prompt", "Select the best option")
        options_from = config.get("options_from")
        allow_regenerate = config.get("allow_regenerate", True)
        step_id = config.get("_step_id", "user_select")
        
        # Substitute template variables
        prompt_text = substitute_template(
            prompt_text,
            ctx.context,
            ctx.asset,
            ctx.step_outputs,
        )
        
        # Find options to choose from
        options = []
        source_output = None
        
        if options_from and options_from in ctx.step_outputs:
            source_output = ctx.step_outputs[options_from]
        else:
            # Look for the most recent step with variations
            for sid in reversed(list(ctx.step_outputs.keys())):
                output = ctx.step_outputs[sid]
                if isinstance(output, dict) and "paths" in output:
                    source_output = output
                    options_from = sid
                    break
        
        if not source_output:
            return StepResult(
                success=False,
                error="No options found for selection",
            )
        
        # Get the list of options (paths or values)
        if isinstance(source_output, dict):
            if "paths" in source_output:
                options = source_output["paths"]
            elif "variations" in source_output:
                options = source_output["variations"]
        
        if not options:
            return StepResult(
                success=False,
                error="No options available for selection",
            )
        
        # Get asset info
        asset_id = ctx.asset.get("id") if ctx.asset else None
        asset_name = ctx.asset.get("name", ctx.asset.get("id", "item")) if ctx.asset else "item"
        
        # Check for web mode
        bridge = _get_web_bridge()
        
        if bridge:
            # Web mode: send to browser
            web_options = []
            for opt in options:
                if isinstance(opt, (str, Path)):
                    # Make path relative to base_path for serving
                    try:
                        rel_path = str(Path(opt).relative_to(ctx.base_path))
                    except ValueError:
                        rel_path = str(opt)
                    web_options.append({"path": rel_path})
                else:
                    web_options.append({"content": str(opt)})
            
            # Get generation prompt if available from source step
            generation_prompt = ""
            if source_output and isinstance(source_output, dict):
                generation_prompt = source_output.get("prompt", "")
            
            # Determine step type from source
            step_type = "user_select"
            if options_from and options_from in ctx.step_outputs:
                src = ctx.step_outputs[options_from]
                if isinstance(src, dict) and src.get("type"):
                    step_type = src["type"]
            
            selected_index, regenerate = await bridge.request_selection(
                step_id=step_id,
                asset_name=asset_name,
                options=web_options,
                asset_id=asset_id,
                prompt=prompt_text,
                step_type=step_type,
                generation_prompt=generation_prompt,
                step_description=f"Choose the best result from {len(options)} variations",
                metadata={
                    "options_from": options_from,
                    "total_options": len(options),
                },
            )
            
            if regenerate:
                return StepResult(
                    success=True,
                    output={"action": "regenerate"},
                    duration_ms=int((time.time() - start) * 1000),
                )
            
            selected_option = options[selected_index]
            return StepResult(
                success=True,
                output={
                    "selected_index": selected_index,
                    "selected_path": selected_option if isinstance(selected_option, str) else str(selected_option),
                    "action": "select",
                },
                selected_index=selected_index,
                duration_ms=int((time.time() - start) * 1000),
            )
        
        # CLI mode: terminal prompt
        console.print()
        console.print(Panel(
            f"[bold]{prompt_text}[/bold]",
            title=f"🎨 Selection for {asset_name}",
            border_style="blue"
        ))
        
        # Create options table
        table = Table(show_header=True)
        table.add_column("#", style="cyan", width=4)
        table.add_column("Option", style="white")
        
        for i, option in enumerate(options, 1):
            # For file paths, show relative path
            if isinstance(option, (str, Path)):
                display = str(option)
                if ctx.state_dir:
                    try:
                        display = str(Path(option).relative_to(ctx.base_path))
                    except ValueError:
                        pass
            else:
                display = str(option)
            
            table.add_row(str(i), display)
        
        if allow_regenerate:
            table.add_row("r", "[yellow]Regenerate all[/yellow]")
        
        console.print(table)
        console.print()
        
        # Get user choice
        valid_choices = list(range(1, len(options) + 1))
        
        while True:
            choice = Prompt.ask(
                "Enter your choice",
                default="1"
            )
            
            if allow_regenerate and choice.lower() == 'r':
                return StepResult(
                    success=True,
                    output={"action": "regenerate"},
                    duration_ms=int((time.time() - start) * 1000),
                )
            
            try:
                choice_int = int(choice)
                if choice_int in valid_choices:
                    break
                console.print(f"[red]Please enter a number between 1 and {len(options)}[/red]")
            except ValueError:
                console.print("[red]Invalid input. Enter a number or 'r' to regenerate.[/red]")
        
        selected_index = choice_int - 1
        selected_option = options[selected_index]
        
        console.print(f"[green]✓ Selected option {choice_int}[/green]")
        
        duration = int((time.time() - start) * 1000)
        
        return StepResult(
            success=True,
            output={
                "selected_index": selected_index,
                "selected_path": selected_option if isinstance(selected_option, str) else str(selected_option),
                "action": "select",
            },
            selected_index=selected_index,
            duration_ms=duration,
        )


@register_executor("user_approve")
class UserApproveExecutor(StepExecutor):
    """Execute user approval steps (CLI or web mode)."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute a user approval step.
        
        Config:
            prompt: Message to display to user
            show_path: Path of artifact to show for approval
            max_attempts: Maximum regeneration attempts (default: 5)
        """
        import time
        start = time.time()
        
        prompt_text = config.get("prompt", "Do you approve this result?")
        max_attempts = config.get("max_attempts", 5)
        step_id = config.get("_step_id", "user_approve")
        
        # Substitute template variables
        prompt_text = substitute_template(
            prompt_text,
            ctx.context,
            ctx.asset,
            ctx.step_outputs,
        )
        
        # Find what we're approving
        artifact_path = config.get("show_path")
        
        if not artifact_path:
            # Look for most recent image output
            for sid in reversed(list(ctx.step_outputs.keys())):
                output = ctx.step_outputs[sid]
                if isinstance(output, dict):
                    if "selected_path" in output:
                        artifact_path = output["selected_path"]
                        break
                    elif "path" in output:
                        artifact_path = output["path"]
                        break
                    elif "paths" in output and output["paths"]:
                        artifact_path = output["paths"][0]
                        break
        
        # Get asset info
        asset_id = ctx.asset.get("id") if ctx.asset else None
        asset_name = ctx.asset.get("name", ctx.asset.get("id", "item")) if ctx.asset else "item"
        
        # Check for web mode
        bridge = _get_web_bridge()
        
        if bridge:
            # Web mode: send to browser
            result = {}
            generation_prompt = ""
            if artifact_path:
                try:
                    rel_path = str(Path(artifact_path).relative_to(ctx.base_path))
                except ValueError:
                    rel_path = str(artifact_path)
                result["path"] = rel_path
            
            # Try to find the generation prompt from previous step outputs
            for sid in reversed(list(ctx.step_outputs.keys())):
                output = ctx.step_outputs[sid]
                if isinstance(output, dict) and "prompt" in output:
                    generation_prompt = output["prompt"]
                    break
            
            approved, regenerate = await bridge.request_approval(
                step_id=step_id,
                asset_name=asset_name,
                result=result,
                asset_id=asset_id,
                prompt=prompt_text,
                step_type="user_approve",
                generation_prompt=generation_prompt,
                step_description="Review and approve the generated result, or reject to regenerate",
            )
            
            duration = int((time.time() - start) * 1000)
            
            if approved:
                return StepResult(
                    success=True,
                    output={"approved": True, "action": "approve"},
                    duration_ms=duration,
                )
            else:
                return StepResult(
                    success=True,
                    output={"approved": False, "action": "reject"},
                    duration_ms=duration,
                )
        
        # CLI mode: terminal prompt
        console.print()
        console.print(Panel(
            f"[bold]{prompt_text}[/bold]",
            title=f"✅ Approval for {asset_name}",
            border_style="green"
        ))
        
        if artifact_path:
            try:
                rel_path = str(Path(artifact_path).relative_to(ctx.base_path))
            except ValueError:
                rel_path = str(artifact_path)
            console.print(f"  Artifact: [cyan]{rel_path}[/cyan]")
        
        console.print()
        
        # Get user decision
        approved = Confirm.ask("Approve?", default=True)
        
        duration = int((time.time() - start) * 1000)
        
        if approved:
            console.print("[green]✓ Approved[/green]")
            return StepResult(
                success=True,
                output={"approved": True, "action": "approve"},
                duration_ms=duration,
            )
        else:
            console.print("[yellow]✗ Rejected - will regenerate[/yellow]")
            return StepResult(
                success=True,
                output={"approved": False, "action": "reject"},
                duration_ms=duration,
            )
