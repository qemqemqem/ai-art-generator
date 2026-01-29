"""
Pipeline Specification Parser

Parses and validates YAML pipeline definitions.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


# =============================================================================
# Type System
# =============================================================================

# Built-in primitive types
BUILTIN_TYPES = {"text", "image", "number", "boolean", "list"}


@dataclass
class FieldType:
    """
    Parsed field type.
    
    Examples:
        text        -> FieldType(base="text", optional=False, enum_values=None)
        text?       -> FieldType(base="text", optional=True, enum_values=None)
        list        -> FieldType(base="list", optional=False, enum_values=None)
        common|rare -> FieldType(base="enum", optional=False, enum_values=["common", "rare"])
        MagicCard   -> FieldType(base="MagicCard", optional=False, enum_values=None)
        MagicCard?  -> FieldType(base="MagicCard", optional=True, enum_values=None)
    """
    base: str  # "text", "image", "number", "boolean", "list", "enum", or custom type name
    optional: bool = False
    enum_values: list[str] | None = None
    
    def is_builtin(self) -> bool:
        return self.base in BUILTIN_TYPES or self.base == "enum"
    
    def __str__(self) -> str:
        if self.enum_values:
            s = " | ".join(self.enum_values)
        else:
            s = self.base
        return f"{s}?" if self.optional else s


def parse_field_type(type_str: str) -> FieldType:
    """
    Parse a field type string into a FieldType.
    
    Supports:
        text, image, number, boolean, list  - primitives
        text?                               - optional
        a | b | c                           - enum
        CustomType                          - reference to defined type
        CustomType?                         - optional reference
    """
    type_str = type_str.strip()
    
    # Check for optional marker
    optional = type_str.endswith("?")
    if optional:
        type_str = type_str[:-1].strip()
    
    # Check for enum (contains |)
    if "|" in type_str:
        values = [v.strip() for v in type_str.split("|")]
        return FieldType(base="enum", optional=optional, enum_values=values)
    
    # Otherwise it's a simple type or reference
    return FieldType(base=type_str, optional=optional)


@dataclass
class TypeDef:
    """
    A user-defined type (like a dataclass).
    
    Example:
        MagicCard:
          name: text
          art: image
          rarity: common | uncommon | rare
    """
    name: str
    fields: dict[str, FieldType]
    
    def __str__(self) -> str:
        lines = [f"type {self.name}:"]
        for name, ftype in self.fields.items():
            lines.append(f"  {name}: {ftype}")
        return "\n".join(lines)


def parse_type_def(name: str, fields_data: dict[str, Any]) -> TypeDef:
    """Parse a type definition from YAML data."""
    fields: dict[str, FieldType] = {}
    
    for field_name, field_type_str in fields_data.items():
        # Skip YAML anchor keys (start with _)
        if field_name.startswith("_"):
            continue
        
        if not isinstance(field_type_str, str):
            raise ParseError(
                f"Type '{name}' field '{field_name}' must be a string type, "
                f"got {type(field_type_str).__name__}"
            )
        
        fields[field_name] = parse_field_type(field_type_str)
    
    return TypeDef(name=name, fields=fields)


# =============================================================================
# Step Types
# =============================================================================

class StepType(str, Enum):
    """Valid step types in a pipeline."""
    RESEARCH = "research"
    GENERATE_TEXT = "generate_text"
    GENERATE_NAME = "generate_name"
    GENERATE_PROMPT = "generate_prompt"
    GENERATE_IMAGE = "generate_image"
    GENERATE_SPRITE = "generate_sprite"
    ASSESS = "assess"
    USER_SELECT = "user_select"
    USER_APPROVE = "user_approve"
    REFINE = "refine"
    COMPOSITE = "composite"
    REMOVE_BACKGROUND = "remove_background"
    RESIZE = "resize"
    LOOP = "loop"
    BRANCH = "branch"
    CUSTOM = "custom"


@dataclass
class StepSpec:
    """A single step in the pipeline."""
    id: str
    type: StepType
    requires: list[str] = field(default_factory=list)
    for_each: str | None = None
    gather: bool = False
    condition: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    output: str | None = None  # Which field this step writes to
    
    # State persistence
    save_to: str | None = None  # Path pattern for saving output
    cache: bool | str | None = None   # True, False, "skip_existing", or None for smart defaults
    
    # For loop steps
    steps: list["StepSpec"] | None = None


# =============================================================================
# Assets
# =============================================================================

@dataclass 
class AssetSpec:
    """Specification for what assets we're producing."""
    type: str  # "image", "text", or a custom type name
    count: int | None = None
    items: list[dict[str, Any]] | None = None
    generated_by: str | None = None
    from_file: str | None = None  # External input file path


@dataclass
class StateConfig:
    """Configuration for state/checkpoint persistence."""
    directory: str = ".artgen/"


# =============================================================================
# Pipeline
# =============================================================================

@dataclass
class PipelineSpec:
    """Complete pipeline specification."""
    name: str
    version: str = "1.0"
    description: str = ""
    types: dict[str, TypeDef] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    state: StateConfig = field(default_factory=StateConfig)
    assets: AssetSpec | None = None
    steps: list[StepSpec] = field(default_factory=list)
    
    # Computed
    step_index: dict[str, StepSpec] = field(default_factory=dict, repr=False)


class ParseError(Exception):
    """Error parsing pipeline spec."""
    pass


class ValidationError(Exception):
    """Error validating pipeline spec."""
    pass


def parse_step(data: dict[str, Any], path: str = "") -> StepSpec:
    """Parse a single step from YAML data."""
    if "id" not in data:
        raise ParseError(f"Step missing required 'id' field at {path}")
    if "type" not in data:
        raise ParseError(f"Step '{data['id']}' missing required 'type' field")
    
    try:
        step_type = StepType(data["type"])
    except ValueError:
        valid = ", ".join(t.value for t in StepType)
        raise ParseError(
            f"Step '{data['id']}' has invalid type '{data['type']}'. "
            f"Valid types: {valid}"
        )
    
    # Parse nested steps for loops
    nested_steps = None
    if step_type == StepType.LOOP and "config" in data and "steps" in data["config"]:
        nested_steps = [
            parse_step(s, f"{path}.config.steps[{i}]")
            for i, s in enumerate(data["config"]["steps"])
        ]
    
    return StepSpec(
        id=data["id"],
        type=step_type,
        requires=data.get("requires", []),
        for_each=data.get("for_each"),
        gather=data.get("gather", False),
        condition=data.get("condition"),
        config=data.get("config", {}),
        output=data.get("output"),
        save_to=data.get("save_to"),
        cache=data.get("cache"),  # None enables smart defaults
        steps=nested_steps,
    )


def parse_assets(data: dict[str, Any] | None) -> AssetSpec | None:
    """Parse assets specification."""
    if not data:
        return None
    
    return AssetSpec(
        type=data.get("type", "image"),
        count=data.get("count"),
        items=data.get("items"),
        generated_by=data.get("generated_by"),
        from_file=data.get("from_file"),
    )


def parse_state(data: dict[str, Any] | None) -> StateConfig:
    """Parse state configuration."""
    if not data:
        return StateConfig()
    
    return StateConfig(
        directory=data.get("directory", ".artgen/"),
    )


def parse_types(data: dict[str, Any] | None) -> dict[str, TypeDef]:
    """Parse type definitions."""
    if not data:
        return {}
    
    types: dict[str, TypeDef] = {}
    
    for type_name, fields_data in data.items():
        # Skip YAML anchors (names starting with _)
        if type_name.startswith("_"):
            continue
            
        if not isinstance(fields_data, dict):
            raise ParseError(
                f"Type '{type_name}' must be a mapping of field names to types"
            )
        
        types[type_name] = parse_type_def(type_name, fields_data)
    
    return types


def parse_pipeline(yaml_content: str) -> PipelineSpec:
    """Parse a YAML pipeline specification."""
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise ParseError(f"Invalid YAML: {e}")
    
    if not isinstance(data, dict):
        raise ParseError("Pipeline must be a YAML mapping")
    
    if "name" not in data:
        raise ParseError("Pipeline missing required 'name' field")
    
    # Parse types first (other sections may reference them)
    types = parse_types(data.get("types"))
    
    steps = []
    for i, step_data in enumerate(data.get("steps", [])):
        steps.append(parse_step(step_data, f"steps[{i}]"))
    
    spec = PipelineSpec(
        name=data["name"],
        version=data.get("version", "1.0"),
        description=data.get("description", ""),
        types=types,
        context=data.get("context", {}),
        state=parse_state(data.get("state")),
        assets=parse_assets(data.get("assets")),
        steps=steps,
    )
    
    # Build index
    spec.step_index = {s.id: s for s in steps}
    
    return spec


def validate_pipeline(spec: PipelineSpec) -> list[str]:
    """
    Validate a pipeline specification.
    Returns list of warnings (empty if valid).
    Raises ValidationError for fatal issues.
    """
    warnings = []
    
    # Collect all known type names (builtins + user-defined)
    known_types = BUILTIN_TYPES | set(spec.types.keys())
    
    # Validate type definitions (check field type references)
    for type_def in spec.types.values():
        for field_name, field_type in type_def.fields.items():
            if not field_type.is_builtin() and field_type.base not in spec.types:
                raise ValidationError(
                    f"Type '{type_def.name}' field '{field_name}' references "
                    f"unknown type '{field_type.base}'"
                )
    
    # Validate asset type reference
    if spec.assets:
        asset_type = spec.assets.type
        if asset_type not in known_types:
            raise ValidationError(
                f"Assets reference unknown type '{asset_type}'. "
                f"Define it in the 'types' section or use a builtin: {BUILTIN_TYPES}"
            )
    
    # Check for duplicate step IDs
    seen_ids: set[str] = set()
    for step in spec.steps:
        if step.id in seen_ids:
            raise ValidationError(f"Duplicate step ID: '{step.id}'")
        seen_ids.add(step.id)
    
    # Check requires references
    for step in spec.steps:
        for req in step.requires:
            if req not in spec.step_index:
                raise ValidationError(
                    f"Step '{step.id}' requires non-existent step '{req}'"
                )
    
    # Check for cycles (simple DFS)
    def has_cycle(step_id: str, visiting: set[str], visited: set[str]) -> bool:
        if step_id in visiting:
            return True
        if step_id in visited:
            return False
        
        visiting.add(step_id)
        step = spec.step_index.get(step_id)
        if step:
            for req in step.requires:
                if has_cycle(req, visiting, visited):
                    return True
        visiting.remove(step_id)
        visited.add(step_id)
        return False
    
    visited: set[str] = set()
    for step in spec.steps:
        if has_cycle(step.id, set(), visited):
            raise ValidationError(f"Cycle detected involving step '{step.id}'")
    
    # Check for unreachable steps (warning only)
    roots = {s.id for s in spec.steps if not s.requires}
    if not roots:
        warnings.append("No root steps found (all steps have requires)")
    
    # Check gather steps have something to gather
    for step in spec.steps:
        if step.gather and not step.requires:
            warnings.append(
                f"Step '{step.id}' has gather=true but no requires"
            )
    
    # Check for_each steps reference valid scope
    for step in spec.steps:
        if step.for_each and step.for_each not in ("asset", "item"):
            warnings.append(
                f"Step '{step.id}' has for_each='{step.for_each}', "
                f"expected 'asset' or 'item'"
            )
    
    return warnings


def load_pipeline(path: Path | str) -> PipelineSpec:
    """Load and validate a pipeline from a file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Pipeline file not found: {path}")
    
    content = path.read_text()
    spec = parse_pipeline(content)
    
    # Validate (raises on fatal errors)
    warnings = validate_pipeline(spec)
    for w in warnings:
        print(f"Warning: {w}")
    
    return spec


def get_execution_order(spec: PipelineSpec) -> list[list[str]]:
    """
    Get steps grouped by execution tier.
    Steps in the same tier can run in parallel.
    Returns list of tiers, each tier is a list of step IDs.
    """
    # Kahn's algorithm for topological sort with levels
    in_degree = {s.id: len(s.requires) for s in spec.steps}
    tiers: list[list[str]] = []
    remaining = set(spec.step_index.keys())
    
    while remaining:
        # Find all steps with no remaining dependencies
        ready = [s for s in remaining if in_degree[s] == 0]
        if not ready:
            raise ValidationError("Cycle detected in pipeline")
        
        tiers.append(ready)
        
        # Remove these from remaining and update in_degrees
        for step_id in ready:
            remaining.remove(step_id)
            # Decrease in_degree of dependents
            for other in spec.steps:
                if step_id in other.requires:
                    in_degree[other.id] -= 1
    
    return tiers


def visualize_dag(spec: PipelineSpec) -> str:
    """Generate a simple ASCII visualization of the pipeline DAG."""
    tiers = get_execution_order(spec)
    lines = []
    
    lines.append("Pipeline DAG:")
    lines.append("=" * 60)
    
    for i, tier in enumerate(tiers):
        tier_label = f"Tier {i}"
        
        # Group by for_each
        parallel = [s for s in tier if spec.step_index[s].for_each]
        sequential = [s for s in tier if not spec.step_index[s].for_each]
        
        if sequential:
            lines.append(f"\n{tier_label} (sequential):")
            for step_id in sequential:
                step = spec.step_index[step_id]
                flags = []
                if step.gather:
                    flags.append("GATHER")
                if step.cache:
                    flags.append(f"CACHE:{step.cache}")
                if step.save_to:
                    flags.append(f"→ {step.save_to}")
                flag_str = f" [{', '.join(flags)}]" if flags else ""
                lines.append(f"  [{step_id}] ({step.type.value}){flag_str}")
        
        if parallel:
            lines.append(f"\n{tier_label} (parallel per {spec.step_index[parallel[0]].for_each}):")
            for step_id in parallel:
                step = spec.step_index[step_id]
                extras = []
                if step.condition:
                    extras.append(f"when {step.condition}")
                if step.cache:
                    extras.append(f"cache:{step.cache}")
                if step.save_to:
                    extras.append(f"→ {step.save_to}")
                extra_str = f" [{', '.join(extras)}]" if extras else ""
                lines.append(f"  [{step_id}] ({step.type.value}){extra_str}")
    
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def format_type_def(type_def: TypeDef) -> str:
    """Format a type definition for display."""
    lines = [f"  {type_def.name}:"]
    for field_name, field_type in type_def.fields.items():
        lines.append(f"    {field_name}: {field_type}")
    return "\n".join(lines)


# CLI interface
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python spec_parser.py <pipeline.yaml>")
        sys.exit(1)
    
    path = sys.argv[1]
    
    try:
        spec = load_pipeline(path)
        print(f"✓ Pipeline '{spec.name}' parsed successfully")
        print(f"  Version: {spec.version}")
        
        # Show types
        if spec.types:
            print(f"\nTypes ({len(spec.types)}):")
            for type_def in spec.types.values():
                print(format_type_def(type_def))
        
        # Show state config
        print(f"\nState: {spec.state.directory}")
        
        # Show assets
        if spec.assets:
            print(f"\nAssets: {spec.assets.type}", end="")
            if spec.assets.from_file:
                print(f" (from file: {spec.assets.from_file})")
            elif spec.assets.count:
                print(f" (count: {spec.assets.count})")
            elif spec.assets.items:
                print(f" (items: {len(spec.assets.items)})")
            elif spec.assets.generated_by:
                print(f" (generated by: {spec.assets.generated_by})")
            else:
                print()
        
        print(f"\nSteps: {len(spec.steps)}")
        print()
        print(visualize_dag(spec))
        
    except (ParseError, ValidationError) as e:
        print(f"✗ Error: {e}")
        sys.exit(1)
