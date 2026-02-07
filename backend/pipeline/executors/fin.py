"""
Fin (Finish) Executor.

Handles the final display stage of a pipeline.
Gathers and displays configured outputs (images, text) for a completion view.

Usage in pipeline.yaml:
    - id: finish
      type: fin
      requires: [generate_art, render_full_cards]
      config:
        title: "Pipeline Complete!"
        message: "Your cards have been generated successfully."
        display:
          - step: render_full_cards
            type: images
            label: "Rendered Cards"
          - step: generate_art
            type: images
            label: "Card Art"
          - step: write_flavor_text
            type: text
            label: "Flavor Text"
"""

import json
import time
from pathlib import Path
from typing import Any

from rich.console import Console
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


def _extract_images_from_output(output: Any, base_path: Path) -> list[dict[str, Any]]:
    """Extract image paths from a step output."""
    images = []
    
    if isinstance(output, dict):
        # Check for common image path keys
        for key in ["paths", "images", "image_paths", "output_paths"]:
            if key in output and isinstance(output[key], list):
                for p in output[key]:
                    if isinstance(p, (str, Path)):
                        try:
                            rel_path = str(Path(p).relative_to(base_path))
                        except ValueError:
                            rel_path = str(p)
                        images.append({"path": rel_path})
        
        # Single path
        for key in ["path", "image_path", "selected_path", "output_path"]:
            if key in output and isinstance(output[key], (str, Path)):
                p = output[key]
                try:
                    rel_path = str(Path(p).relative_to(base_path))
                except ValueError:
                    rel_path = str(p)
                images.append({"path": rel_path})
        
        # Per-asset outputs
        if "assets" in output and isinstance(output["assets"], dict):
            for asset_id, asset_output in output["assets"].items():
                asset_images = _extract_images_from_output(asset_output, base_path)
                for img in asset_images:
                    img["asset_id"] = asset_id
                images.extend(asset_images)
    
    return images


def _extract_text_from_output(output: Any) -> list[dict[str, Any]]:
    """Extract text content from a step output."""
    texts = []
    
    if isinstance(output, str):
        texts.append({"content": output})
    elif isinstance(output, dict):
        # Check for text content keys
        for key in ["content", "text", "summary", "result"]:
            if key in output and isinstance(output[key], str):
                texts.append({"content": output[key]})
                break
        
        # Per-asset outputs
        if "assets" in output and isinstance(output["assets"], dict):
            for asset_id, asset_output in output["assets"].items():
                asset_texts = _extract_text_from_output(asset_output)
                for txt in asset_texts:
                    txt["asset_id"] = asset_id
                texts.extend(asset_texts)
    
    return texts


@register_executor("fin")
class FinExecutor(StepExecutor):
    """
    Execute the final display stage.
    
    Gathers configured outputs and displays them in a completion view.
    """
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute the fin stage.
        
        Config:
            title: Title for the completion page (default: "Pipeline Complete!")
            message: Optional completion message
            display: List of display items:
                - step: Step ID to get output from
                  type: "images" or "text"
                  label: Display label (optional)
                  key: Specific output key to use (optional)
        """
        start = time.time()
        
        title = config.get("title", "Pipeline Complete!")
        message = config.get("message", "")
        display_config = config.get("display", [])
        step_id = config.get("_step_id", "fin")
        
        # Substitute template variables
        title = substitute_template(title, ctx.context, ctx.asset, ctx.step_outputs)
        if message:
            message = substitute_template(message, ctx.context, ctx.asset, ctx.step_outputs)
        
        # Gather display items
        display_items = []
        
        for item_config in display_config:
            source_step = item_config.get("step")
            display_type = item_config.get("type", "images")
            label = item_config.get("label", source_step or "Output")
            output_key = item_config.get("key")
            
            if not source_step:
                continue
            
            # Get the source step output
            source_output = ctx.step_outputs.get(source_step)
            if not source_output:
                console.print(f"[yellow]Warning: Step '{source_step}' not found in outputs[/yellow]")
                continue
            
            # If a specific key is requested, extract it
            if output_key and isinstance(source_output, dict):
                source_output = source_output.get(output_key, source_output)
            
            # Extract content based on type
            if display_type == "images":
                images = _extract_images_from_output(source_output, ctx.base_path)
                if images:
                    display_items.append({
                        "type": "images",
                        "label": label,
                        "step": source_step,
                        "items": images,
                    })
            elif display_type == "text":
                texts = _extract_text_from_output(source_output)
                if texts:
                    display_items.append({
                        "type": "text",
                        "label": label,
                        "step": source_step,
                        "items": texts,
                    })
        
        # If no display config, try to auto-detect outputs
        if not display_config:
            for sid, output in ctx.step_outputs.items():
                # Look for image outputs
                images = _extract_images_from_output(output, ctx.base_path)
                if images:
                    display_items.append({
                        "type": "images",
                        "label": sid,
                        "step": sid,
                        "items": images,
                    })
        
        # Build result
        result_output = {
            "title": title,
            "message": message,
            "display_items": display_items,
            "total_images": sum(
                len(item.get("items", []))
                for item in display_items
                if item.get("type") == "images"
            ),
            "total_text_items": sum(
                len(item.get("items", []))
                for item in display_items
                if item.get("type") == "text"
            ),
        }
        
        # Check for web mode
        bridge = _get_web_bridge()
        
        if bridge:
            # Web mode: broadcast fin data for frontend display
            bridge._broadcast("fin_data", result_output)
        
        # CLI mode: display summary
        console.print()
        console.print(Panel(
            f"[bold green]{title}[/bold green]\n\n{message}" if message else f"[bold green]{title}[/bold green]",
            title="🎉 Complete",
            border_style="green"
        ))
        
        # Show what's available
        if display_items:
            console.print("\n[bold]Generated Outputs:[/bold]")
            for item in display_items:
                item_type = item.get("type")
                label = item.get("label", "Output")
                items = item.get("items", [])
                
                if item_type == "images":
                    console.print(f"  📷 [cyan]{label}[/cyan]: {len(items)} images")
                    # Show first few paths
                    for img in items[:3]:
                        console.print(f"      → {img.get('path', 'unknown')}")
                    if len(items) > 3:
                        console.print(f"      [dim]... and {len(items) - 3} more[/dim]")
                elif item_type == "text":
                    console.print(f"  📝 [cyan]{label}[/cyan]: {len(items)} items")
        
        duration = int((time.time() - start) * 1000)
        
        return StepResult(
            success=True,
            output=result_output,
            duration_ms=duration,
        )
