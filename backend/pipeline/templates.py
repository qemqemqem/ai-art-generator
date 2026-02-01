"""
Template Variable Substitution for Pipeline Prompts.

Handles variable interpolation in prompts and config values:
  - {context.style} - Values from context section
  - {asset.name} - Current asset fields
  - {step_id.output} - Output from previous steps

Validation is performed at parse time to catch undefined references.
"""

import re
from dataclasses import dataclass
from typing import Any


class TemplateError(Exception):
    """Error processing a template."""
    pass


@dataclass
class TemplateVariable:
    """A parsed template variable."""
    full_match: str      # The full {namespace.field} string
    namespace: str       # "context", "asset", or a step ID
    field: str          # The field name(s) after the namespace
    

def parse_template_variables(template: str) -> list[TemplateVariable]:
    """
    Parse all template variables from a string.
    
    Args:
        template: String containing {namespace.field} variables
        
    Returns:
        List of parsed variables
    """
    if not template:
        return []
    
    # Match {identifier.field} or {identifier.field.subfield}
    pattern = r'\{([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}'
    
    variables = []
    for match in re.finditer(pattern, template):
        variables.append(TemplateVariable(
            full_match=match.group(0),
            namespace=match.group(1),
            field=match.group(2),
        ))
    
    return variables


def validate_template(
    template: str,
    available_context: set[str],
    available_asset_fields: set[str],
    available_step_outputs: set[str],
) -> list[str]:
    """
    Validate a template's variable references.
    
    Args:
        template: The template string to validate
        available_context: Keys available in context
        available_asset_fields: Fields available on assets
        available_step_outputs: Step IDs with available output
        
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    variables = parse_template_variables(template)
    
    for var in variables:
        if var.namespace == "context":
            # Check context.field
            if var.field not in available_context:
                errors.append(f"Unknown context field: {var.full_match}")
        elif var.namespace == "asset":
            # Check asset.field (allow nested like asset.stats.health)
            root_field = var.field.split('.')[0]
            if root_field not in available_asset_fields:
                errors.append(f"Unknown asset field: {var.full_match}")
        elif var.namespace == "ctx":
            # ctx is an alias for context
            if var.field not in available_context:
                errors.append(f"Unknown context field: {var.full_match}")
        else:
            # Assume it's a step ID reference
            if var.namespace not in available_step_outputs:
                errors.append(f"Unknown step output: {var.full_match}")
    
    return errors


def substitute_template(
    template: str,
    context: dict[str, Any],
    asset: dict[str, Any] | None = None,
    step_outputs: dict[str, Any] | None = None,
) -> str:
    """
    Substitute variables in a template string.
    
    Args:
        template: String with {namespace.field} variables
        context: Pipeline context values
        asset: Current asset data (for per-asset steps)
        step_outputs: Outputs from previous steps, keyed by step ID
        
    Returns:
        String with variables substituted
        
    Raises:
        TemplateError: If a variable cannot be resolved
    """
    if not template:
        return template
    
    step_outputs = step_outputs or {}
    asset = asset or {}
    
    def get_nested_value(data: dict, path: str) -> Any:
        """Get a nested value using dot notation."""
        parts = path.split('.')
        current = data
        for part in parts:
            if isinstance(current, dict):
                if part not in current:
                    return None
                current = current[part]
            else:
                return None
        return current
    
    def replacer(match: re.Match) -> str:
        namespace = match.group(1)
        field = match.group(2)
        
        if namespace in ("context", "ctx"):
            value = get_nested_value(context, field)
            if value is None:
                raise TemplateError(f"Context field not found: {namespace}.{field}")
            return format_value(value)
        
        elif namespace == "asset":
            value = get_nested_value(asset, field)
            if value is None:
                # Check if it's an optional field
                return ""
            return format_value(value)
        
        elif namespace == "step_outputs":
            # {step_outputs.step_id} or {step_outputs.step_id.field}
            # The first part of field is the step ID
            parts = field.split('.', 1)
            step_id = parts[0]
            subfield = parts[1] if len(parts) > 1 else None
            
            if step_id not in step_outputs:
                raise TemplateError(f"Step output not found: step_outputs.{step_id}")
            
            step_output = step_outputs[step_id]
            
            if subfield:
                value = get_nested_value(step_output, subfield)
            else:
                # Get the primary content from the step output
                if isinstance(step_output, dict):
                    value = step_output.get("content") or step_output.get("output") or step_output
                else:
                    value = step_output
            
            if value is None:
                return ""
            return format_value(value)
        
        else:
            # Direct step output reference: {step_id.field}
            if namespace not in step_outputs:
                raise TemplateError(f"Step output not found: {namespace}")
            
            step_output = step_outputs[namespace]
            if field == "output":
                # Default output
                value = step_output.get("output") or step_output.get("content") or step_output
            else:
                value = get_nested_value(step_output, field)
            
            if value is None:
                return ""
            return format_value(value)
    
    # Pattern for {namespace.field} or {namespace.field.subfield}
    pattern = r'\{([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}'
    
    return re.sub(pattern, replacer, template)


def format_value(value: Any) -> str:
    """
    Format a value for template substitution.
    
    Args:
        value: The value to format
        
    Returns:
        String representation
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, tuple)):
        return ", ".join(format_value(v) for v in value)
    if isinstance(value, dict):
        # For dicts, format as key-value pairs
        return ", ".join(f"{k}: {format_value(v)}" for k, v in value.items())
    return str(value)


def substitute_all(
    data: Any,
    context: dict[str, Any],
    asset: dict[str, Any] | None = None,
    step_outputs: dict[str, Any] | None = None,
) -> Any:
    """
    Recursively substitute templates in a data structure.
    
    Handles strings, lists, and dicts.
    
    Args:
        data: Data structure containing template strings
        context: Pipeline context values
        asset: Current asset data
        step_outputs: Outputs from previous steps
        
    Returns:
        Data structure with templates substituted
    """
    if isinstance(data, str):
        return substitute_template(data, context, asset, step_outputs)
    elif isinstance(data, dict):
        return {
            k: substitute_all(v, context, asset, step_outputs)
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [substitute_all(v, context, asset, step_outputs) for v in data]
    else:
        return data
