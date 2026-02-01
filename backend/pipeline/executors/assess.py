"""
Image Assessment Executor.

Uses AI vision to evaluate images for:
  - Quality and clarity
  - Adherence to prompt/requirements
  - Technical issues (artifacts, noise, etc.)
  - Style consistency
"""

from pathlib import Path
from typing import Any

from PIL import Image
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .base import ExecutorContext, StepExecutor, StepResult
from .registry import register_executor
from ..templates import substitute_template

console = Console()


@register_executor("assess")
class AssessImageExecutor(StepExecutor):
    """Execute image assessment using AI vision."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute an image assessment step.
        
        Config:
            source_step: Step ID containing the image to assess (optional)
            image_path: Direct path to image (optional)
            criteria: What to assess for (optional)
            scoring: Return numeric score (default: True)
            threshold: Minimum score to pass (default: 7)
        """
        import time
        start = time.time()
        
        source_step = config.get("source_step")
        criteria = config.get("criteria", "")
        scoring = config.get("scoring", True)
        threshold = config.get("threshold", 7)
        
        # Substitute template variables in criteria
        if criteria:
            criteria = substitute_template(
                criteria,
                ctx.context,
                ctx.asset,
                ctx.step_outputs,
            )
        
        # Find the image to assess
        image_path = self._find_image_path(config, ctx, source_step)
        
        if not image_path or not Path(image_path).exists():
            return StepResult(
                success=False,
                error=f"Image not found for assessment: {image_path}",
            )
        
        # Build assessment prompt
        prompt = self._build_assessment_prompt(config, ctx, criteria, scoring)
        
        try:
            # Load the image
            img = Image.open(image_path)
            
            # Use Gemini for vision assessment
            from google import genai
            from app.config import get_config
            
            app_config = get_config()
            client = genai.Client(api_key=app_config.providers.google_api_key)
            
            # Send image + prompt to Gemini
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[img, prompt],
            )
            
            assessment_text = response.text if response.text else "No assessment returned"
            
            # Parse score if scoring enabled
            score = None
            passed = True
            
            if scoring:
                score = self._extract_score(assessment_text)
                passed = score >= threshold if score is not None else True
            
            # Display assessment to user
            self._display_assessment(image_path, assessment_text, score, threshold, passed, ctx)
            
            duration = int((time.time() - start) * 1000)
            
            return StepResult(
                success=True,
                output={
                    "assessment": assessment_text,
                    "score": score,
                    "passed": passed,
                    "threshold": threshold,
                    "image_path": str(image_path),
                },
                duration_ms=duration,
                prompt=prompt,
            )
            
        except Exception as e:
            return StepResult(
                success=False,
                error=str(e),
            )
    
    def _find_image_path(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
        source_step: str | None,
    ) -> str | None:
        """Find the image path to assess from config or previous steps."""
        
        # Direct path specified
        if "image_path" in config:
            path = config["image_path"]
            # Handle template substitution in path
            return substitute_template(
                path,
                ctx.context,
                ctx.asset,
                ctx.step_outputs,
            )
        
        # Get the asset ID for per-asset lookups
        asset_id = ctx.asset.get("id") if ctx.asset else None
        
        # Source step specified
        if source_step and source_step in ctx.step_outputs:
            output = ctx.step_outputs[source_step]
            path = self._extract_path_from_per_asset_output(output, asset_id)
            if path:
                return path
        
        # Auto-detect from recent steps
        for step_id in reversed(list(ctx.step_outputs.keys())):
            output = ctx.step_outputs[step_id]
            path = self._extract_path_from_per_asset_output(output, asset_id)
            if path:
                return path
        
        return None
    
    def _extract_path_from_per_asset_output(
        self,
        output: Any,
        asset_id: str | None,
    ) -> str | None:
        """Extract path from per-asset step output structure."""
        if not isinstance(output, dict):
            return None
        
        # Handle per-asset output structure: {"assets": {"asset_id": {...}}}
        if "assets" in output and asset_id:
            asset_output = output["assets"].get(asset_id)
            if asset_output:
                path = self._extract_path_from_output(asset_output)
                if path:
                    return path
        
        # Fallback to direct extraction (for global steps or direct output)
        return self._extract_path_from_output(output)
    
    def _extract_path_from_output(self, output: Any) -> str | None:
        """Extract an image path from step output."""
        if not isinstance(output, dict):
            return None
        
        # Check for various path keys
        if "selected_path" in output:
            return output["selected_path"]
        if "path" in output:
            return output["path"]
        if "paths" in output and output["paths"]:
            return output["paths"][0]
        
        return None
    
    def _build_assessment_prompt(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
        criteria: str,
        scoring: bool,
    ) -> str:
        """Build the assessment prompt for the vision model."""
        
        parts = ["Analyze this image and provide an assessment."]
        
        # Add asset context
        if ctx.asset:
            asset_name = ctx.asset.get("name", "")
            asset_desc = ctx.asset.get("description", ctx.asset.get("prompt", ""))
            if asset_name or asset_desc:
                parts.append(f"\nThis image is supposed to be: {asset_name} - {asset_desc}")
        
        # Add style context
        if ctx.context.get("art_style") or ctx.context.get("style"):
            style = ctx.context.get("art_style", ctx.context.get("style", ""))
            parts.append(f"\nExpected style: {style}")
        
        # Add custom criteria
        if criteria:
            parts.append(f"\nSpecific criteria to assess:\n{criteria}")
        
        # Add evaluation dimensions
        parts.append("""
Evaluate:
1. Visual Quality - Sharpness, clarity, no artifacts
2. Adherence to Description - Does it match what was requested?
3. Style Consistency - Does it match the expected style?
4. Composition - Is the subject well-framed and centered?
5. Technical Issues - Any glitches, text artifacts, or malformed elements?""")
        
        if scoring:
            parts.append("""
At the end of your assessment, provide an overall score from 1-10.
Format: "SCORE: X/10"
""")
        
        return "\n".join(parts)
    
    def _extract_score(self, assessment_text: str) -> int | None:
        """Extract numeric score from assessment text."""
        import re
        
        # Look for patterns like "SCORE: 8/10" or "8/10" or "Score: 8"
        patterns = [
            r"SCORE:\s*(\d+)\s*/\s*10",
            r"Score:\s*(\d+)\s*/\s*10",
            r"(\d+)\s*/\s*10",
            r"score.*?(\d+)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, assessment_text, re.IGNORECASE)
            if match:
                score = int(match.group(1))
                if 1 <= score <= 10:
                    return score
        
        return None
    
    def _display_assessment(
        self,
        image_path: str,
        assessment: str,
        score: int | None,
        threshold: int,
        passed: bool,
        ctx: ExecutorContext,
    ) -> None:
        """Display the assessment results to the user."""
        
        asset_name = ""
        if ctx.asset:
            asset_name = ctx.asset.get("name", ctx.asset.get("id", ""))
        
        # Build panel title
        title = f"Assessment"
        if asset_name:
            title = f"Assessment: {asset_name}"
        
        # Build content
        content_parts = []
        
        # Show image path
        try:
            rel_path = str(Path(image_path).relative_to(ctx.base_path))
        except ValueError:
            rel_path = str(image_path)
        content_parts.append(f"[dim]Image: {rel_path}[/dim]")
        content_parts.append("")
        
        # Show score prominently if available
        if score is not None:
            if passed:
                score_text = f"[bold green]SCORE: {score}/10 ✓[/bold green]"
            else:
                score_text = f"[bold red]SCORE: {score}/10 ✗[/bold red] (threshold: {threshold})"
            content_parts.append(score_text)
            content_parts.append("")
        
        # Show truncated assessment
        assessment_lines = assessment.strip().split("\n")
        if len(assessment_lines) > 10:
            assessment_preview = "\n".join(assessment_lines[:10]) + "\n[dim]...(truncated)[/dim]"
        else:
            assessment_preview = assessment
        content_parts.append(assessment_preview)
        
        border_style = "green" if passed else "red"
        
        console.print()
        console.print(Panel(
            "\n".join(content_parts),
            title=title,
            border_style=border_style,
        ))
