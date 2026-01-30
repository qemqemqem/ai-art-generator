"""
Pipeline Input Validation.

Validates pipeline specifications before execution:
  - Pipeline file structure
  - Environment variables (API keys)
  - External file references
  - Asset definitions
  - Template variable references
  - Step configuration
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .spec_parser import (
    PipelineSpec,
    StepSpec,
    StepType,
    load_pipeline,
    ParseError,
    ValidationError,
)

console = Console()


@dataclass
class ValidationResult:
    """Result of validation."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    
    def add_error(self, msg: str):
        self.errors.append(msg)
        self.valid = False
    
    def add_warning(self, msg: str):
        self.warnings.append(msg)


def validate_environment() -> ValidationResult:
    """
    Validate required environment variables.
    
    Checks for API keys needed by providers.
    """
    result = ValidationResult(valid=True)
    
    # Required for Gemini image generation (supports both env var names)
    if not os.environ.get("GOOGLE_API_KEY") and not os.environ.get("GEMINI_API_KEY"):
        result.add_error(
            "GOOGLE_API_KEY or GEMINI_API_KEY environment variable not set. "
            "Required for image generation with Gemini."
        )
    
    # Optional but recommended
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
        result.add_warning(
            "No OPENAI_API_KEY or ANTHROPIC_API_KEY set. "
            "Text generation will use Gemini (slower)."
        )
    
    return result


def validate_pipeline_file(path: Path) -> ValidationResult:
    """
    Validate a pipeline file can be loaded and parsed.
    """
    result = ValidationResult(valid=True)
    
    if not path.exists():
        result.add_error(f"Pipeline file not found: {path}")
        return result
    
    if not path.is_file():
        result.add_error(f"Pipeline path is not a file: {path}")
        return result
    
    # Check extension
    if path.suffix not in (".yaml", ".yml"):
        result.add_warning(f"Pipeline file has unusual extension: {path.suffix}")
    
    # Try to parse
    try:
        content = path.read_text()
        if not content.strip():
            result.add_error("Pipeline file is empty")
            return result
    except Exception as e:
        result.add_error(f"Cannot read pipeline file: {e}")
        return result
    
    return result


def validate_external_files(spec: PipelineSpec, base_path: Path) -> ValidationResult:
    """
    Validate external file references exist.
    """
    result = ValidationResult(valid=True)
    
    # Check assets from_file
    if spec.assets and spec.assets.from_file:
        file_path = base_path / spec.assets.from_file
        if not file_path.exists():
            result.add_error(
                f"Assets from_file not found: {spec.assets.from_file}\n"
                f"  Expected at: {file_path}"
            )
        elif file_path.stat().st_size == 0:
            result.add_error(f"Assets file is empty: {spec.assets.from_file}")
    
    return result


def validate_assets(spec: PipelineSpec, base_path: Path) -> ValidationResult:
    """
    Validate asset definitions.
    """
    result = ValidationResult(valid=True)
    
    if not spec.assets:
        result.add_warning("No assets defined in pipeline")
        return result
    
    # Check inline items
    if spec.assets.items:
        seen_ids: set[str] = set()
        for i, item in enumerate(spec.assets.items):
            if not isinstance(item, dict):
                result.add_error(f"Asset item {i} is not a mapping")
                continue
            
            # Check for id
            item_id = item.get("id")
            if not item_id:
                result.add_warning(f"Asset item {i} has no 'id' field")
            elif item_id in seen_ids:
                result.add_error(f"Duplicate asset id: '{item_id}'")
            else:
                seen_ids.add(item_id)
            
            # Check for name or description
            if not item.get("name") and not item.get("description") and not item.get("prompt"):
                result.add_warning(
                    f"Asset '{item_id or i}' has no name, description, or prompt"
                )
    
    # Check count
    if spec.assets.count is not None and spec.assets.count < 1:
        result.add_error(f"Asset count must be positive, got {spec.assets.count}")
    
    return result


def validate_template_references(
    spec: PipelineSpec,
    base_path: Path,
) -> ValidationResult:
    """
    Validate template variable references in step configs.
    """
    result = ValidationResult(valid=True)
    
    # Collect available namespaces
    context_keys = set(spec.context.keys())
    
    # Asset fields (from first item or type definition)
    asset_fields: set[str] = {"id", "name", "description", "prompt"}
    if spec.assets and spec.assets.items:
        for item in spec.assets.items:
            asset_fields.update(item.keys())
    
    # Track step outputs that become available
    available_steps: set[str] = set()
    
    # Pattern for template variables
    template_pattern = re.compile(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}')
    
    def check_templates(data: Any, step_id: str, path: str = ""):
        """Recursively check templates in data structure."""
        if isinstance(data, str):
            for match in template_pattern.finditer(data):
                namespace = match.group(1)
                field = match.group(2)
                
                if namespace in ("context", "ctx"):
                    if field not in context_keys:
                        result.add_warning(
                            f"Step '{step_id}' references unknown context.{field}"
                        )
                elif namespace == "asset":
                    root_field = field.split('.')[0]
                    if root_field not in asset_fields:
                        result.add_warning(
                            f"Step '{step_id}' references unknown asset.{root_field}"
                        )
                else:
                    # Assume it's a step reference
                    if namespace not in available_steps:
                        result.add_error(
                            f"Step '{step_id}' references '{namespace}' which "
                            f"hasn't been defined yet. Check step ordering."
                        )
        elif isinstance(data, dict):
            for key, value in data.items():
                check_templates(value, step_id, f"{path}.{key}")
        elif isinstance(data, list):
            for i, item in enumerate(data):
                check_templates(item, step_id, f"{path}[{i}]")
    
    # Check each step in order
    for step in spec.steps:
        # Check config templates
        check_templates(step.config, step.id, "config")
        
        # Check condition templates
        if step.condition:
            check_templates(step.condition, step.id, "condition")
        
        # This step's output is now available
        available_steps.add(step.id)
    
    return result


def validate_step_configs(spec: PipelineSpec) -> ValidationResult:
    """
    Validate step configurations.
    """
    result = ValidationResult(valid=True)
    
    for step in spec.steps:
        # Check required config fields by step type
        config = step.config
        
        if step.type == StepType.RESEARCH:
            if "query" not in config:
                result.add_warning(f"Step '{step.id}' (research) has no 'query' config")
        
        elif step.type == StepType.GENERATE_TEXT:
            if "prompt" not in config:
                result.add_warning(f"Step '{step.id}' (generate_text) has no 'prompt' config")
        
        elif step.type == StepType.GENERATE_IMAGE:
            if "prompt" not in config:
                result.add_warning(f"Step '{step.id}' (generate_image) has no 'prompt' config")
        
        elif step.type == StepType.ASSESS:
            # Assess can work without explicit config
            pass
        
        # Check variations
        if step.variations is not None:
            if step.variations < 1:
                result.add_error(f"Step '{step.id}' variations must be >= 1")
            elif step.variations > 10:
                result.add_warning(f"Step '{step.id}' has high variations ({step.variations})")
        
        # Check max_attempts
        if step.max_attempts < 1:
            result.add_error(f"Step '{step.id}' max_attempts must be >= 1")
        
        # Check until value
        if step.until and step.until != "approved":
            result.add_error(
                f"Step '{step.id}' has invalid until value: '{step.until}'. "
                f"Only 'approved' is supported."
            )
        
        # Check select value
        if step.select and step.select != "user":
            result.add_error(
                f"Step '{step.id}' has invalid select value: '{step.select}'. "
                f"Only 'user' is supported."
            )
    
    return result


def validate_all(
    pipeline_path: Path,
    check_env: bool = True,
) -> tuple[ValidationResult, PipelineSpec | None]:
    """
    Run all validation checks.
    
    Args:
        pipeline_path: Path to the pipeline file
        check_env: Whether to check environment variables
        
    Returns:
        Tuple of (combined result, parsed spec if successful)
    """
    combined = ValidationResult(valid=True)
    spec: PipelineSpec | None = None
    base_path = pipeline_path.parent
    
    # Check environment
    if check_env:
        env_result = validate_environment()
        combined.errors.extend(env_result.errors)
        combined.warnings.extend(env_result.warnings)
        if not env_result.valid:
            combined.valid = False
    
    # Check file
    file_result = validate_pipeline_file(pipeline_path)
    combined.errors.extend(file_result.errors)
    combined.warnings.extend(file_result.warnings)
    if not file_result.valid:
        combined.valid = False
        return combined, None
    
    # Try to parse
    try:
        spec = load_pipeline(pipeline_path)
    except (ParseError, ValidationError) as e:
        combined.add_error(f"Pipeline parse error: {e}")
        return combined, None
    
    # Validate external files
    files_result = validate_external_files(spec, base_path)
    combined.errors.extend(files_result.errors)
    combined.warnings.extend(files_result.warnings)
    if not files_result.valid:
        combined.valid = False
    
    # Validate assets
    assets_result = validate_assets(spec, base_path)
    combined.errors.extend(assets_result.errors)
    combined.warnings.extend(assets_result.warnings)
    if not assets_result.valid:
        combined.valid = False
    
    # Validate templates
    templates_result = validate_template_references(spec, base_path)
    combined.errors.extend(templates_result.errors)
    combined.warnings.extend(templates_result.warnings)
    if not templates_result.valid:
        combined.valid = False
    
    # Validate step configs
    steps_result = validate_step_configs(spec)
    combined.errors.extend(steps_result.errors)
    combined.warnings.extend(steps_result.warnings)
    if not steps_result.valid:
        combined.valid = False
    
    return combined, spec


def print_validation_result(result: ValidationResult, verbose: bool = False):
    """Print validation results to console."""
    
    if result.valid and not result.warnings:
        console.print("[green]✓ Validation passed[/green]")
        return
    
    if result.errors:
        console.print(Panel(
            "\n".join(f"• {e}" for e in result.errors),
            title="[red]Validation Errors[/red]",
            border_style="red",
        ))
    
    if result.warnings and (verbose or not result.valid):
        console.print(Panel(
            "\n".join(f"• {w}" for w in result.warnings),
            title="[yellow]Warnings[/yellow]",
            border_style="yellow",
        ))
    
    if result.valid:
        console.print("[green]✓ Validation passed with warnings[/green]")
    else:
        console.print("[red]✗ Validation failed[/red]")
