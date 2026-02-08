"""
Rich Context Builder for LLM Prompts.

Automatically builds context for LLM steps including:
  - All global/gather step outputs
  - All previous asset-related outputs for the current asset
  - Pipeline context variables
  - Asset definition

This ensures LLMs have full awareness without requiring explicit template references.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class RichContext:
    """
    Assembled context for an LLM step execution.
    """
    # Pipeline-level context
    pipeline_name: str
    pipeline_description: str
    global_context: dict[str, Any]
    
    # Outputs from global/gather steps
    gather_outputs: dict[str, Any]
    
    # Asset-specific context (for per-asset steps)
    asset: dict[str, Any] | None
    asset_outputs: dict[str, Any]  # Previous step outputs for this asset
    
    def to_system_prompt(self) -> str:
        """Build a system prompt section with all context."""
        parts = []
        
        # Pipeline context
        if self.global_context:
            parts.append("## Project Context")
            for key, value in self.global_context.items():
                parts.append(f"- {key}: {_format_value(value)}")
        
        # Gather/global outputs
        if self.gather_outputs:
            parts.append("\n## Background Information")
            for step_id, output in self.gather_outputs.items():
                content = _extract_content(output)
                if content:
                    parts.append(f"\n### {step_id}")
                    parts.append(content)
        
        # Asset context
        if self.asset:
            parts.append("\n## Current Asset")
            for key, value in self.asset.items():
                if key != "id":
                    parts.append(f"- {key}: {_format_value(value)}")
        
        # Asset-specific outputs from previous steps
        if self.asset_outputs:
            parts.append("\n## Previous Steps for This Asset")
            for step_id, output in self.asset_outputs.items():
                content = _extract_content(output)
                if content:
                    parts.append(f"\n### {step_id}")
                    parts.append(content)
        
        return "\n".join(parts)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to a flat dictionary for template substitution."""
        result = {
            "context": self.global_context,
            "ctx": self.global_context,  # Alias
        }
        
        # Add gather outputs
        for step_id, output in self.gather_outputs.items():
            result[step_id] = output
        
        # Add asset
        if self.asset:
            result["asset"] = self.asset
        
        # Add asset-specific outputs
        for step_id, output in self.asset_outputs.items():
            # Merge with or override gather outputs
            if step_id not in result:
                result[step_id] = output
            else:
                # Prefer asset-specific output over global
                result[step_id] = output
        
        return result


def build_rich_context(
    pipeline_name: str,
    pipeline_description: str,
    global_context: dict[str, Any],
    step_outputs: dict[str, Any],
    step_specs: dict[str, Any],
    asset: dict[str, Any] | None = None,
) -> RichContext:
    """
    Build rich context for an LLM step.
    
    Args:
        pipeline_name: Name of the pipeline
        pipeline_description: Description of the pipeline
        global_context: The context section from the pipeline
        step_outputs: All step outputs so far
        step_specs: Step specifications (to determine global vs per-asset)
        asset: The current asset (for per-asset steps)
        
    Returns:
        RichContext with all relevant information assembled
    """
    gather_outputs: dict[str, Any] = {}
    asset_outputs: dict[str, Any] = {}
    
    asset_id = asset.get("id") if asset else None
    
    for step_id, output in step_outputs.items():
        step_spec = step_specs.get(step_id)
        
        # Check if this is a per-asset step
        is_per_asset = (
            step_spec and 
            hasattr(step_spec, 'for_each') and 
            bool(step_spec.for_each)
        )
        
        if is_per_asset:
            # Per-asset step - extract this asset's output
            if isinstance(output, dict) and "assets" in output:
                if asset_id and asset_id in output["assets"]:
                    asset_outputs[step_id] = output["assets"][asset_id]
            else:
                # Direct output (shouldn't happen but handle it)
                asset_outputs[step_id] = output
        else:
            # Global/gather step - include in gather outputs
            gather_outputs[step_id] = output
    
    return RichContext(
        pipeline_name=pipeline_name,
        pipeline_description=pipeline_description,
        global_context=global_context,
        gather_outputs=gather_outputs,
        asset=asset,
        asset_outputs=asset_outputs,
    )


def get_asset_aware_step_outputs(
    step_outputs: dict[str, Any],
    step_specs: dict[str, Any],
    asset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Get step outputs with asset-awareness.
    
    For per-asset steps, extracts the current asset's output.
    For global steps, returns the output as-is.
    
    This is used for template substitution so {step_id.field}
    correctly accesses per-asset outputs when in a per-asset context.
    
    Args:
        step_outputs: All step outputs
        step_specs: Step specifications
        asset: Current asset (for per-asset steps)
        
    Returns:
        Flattened step outputs for the current context
    """
    result: dict[str, Any] = {}
    asset_id = asset.get("id") if asset else None
    
    for step_id, output in step_outputs.items():
        step_spec = step_specs.get(step_id)
        
        # Check if this is a per-asset step
        is_per_asset = (
            step_spec and 
            hasattr(step_spec, 'for_each') and 
            bool(step_spec.for_each)
        )
        
        if is_per_asset and isinstance(output, dict) and "assets" in output:
            # Extract this asset's output
            if asset_id and asset_id in output["assets"]:
                result[step_id] = output["assets"][asset_id]
            # If no asset match, still include the structure for template access
            else:
                result[step_id] = output
        else:
            # Global step or direct output
            result[step_id] = output
    
    return result


def _format_value(value: Any) -> str:
    """Format a value for display in context."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def _extract_content(output: Any) -> str | None:
    """Extract the main content from a step output."""
    if isinstance(output, str):
        return output
    
    if isinstance(output, dict):
        # Try common content keys
        for key in ["content", "text", "result", "output", "prompt"]:
            if key in output and output[key]:
                return str(output[key])
        
        # Try to get any string value
        for value in output.values():
            if isinstance(value, str) and len(value) > 20:
                return value
    
    return None
