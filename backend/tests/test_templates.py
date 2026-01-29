"""Tests for the template substitution system."""

import pytest
from pipeline.templates import (
    TemplateError,
    parse_template_variables,
    substitute_template,
    substitute_all,
    validate_template,
)


class TestParseTemplateVariables:
    """Tests for parsing template variables."""
    
    def test_simple_variable(self):
        """Test parsing a simple variable."""
        vars = parse_template_variables("{context.style}")
        
        assert len(vars) == 1
        assert vars[0].namespace == "context"
        assert vars[0].field == "style"
        assert vars[0].full_match == "{context.style}"
    
    def test_multiple_variables(self):
        """Test parsing multiple variables."""
        template = "{context.style}, {asset.name}, {research.output}"
        vars = parse_template_variables(template)
        
        assert len(vars) == 3
        namespaces = [v.namespace for v in vars]
        assert "context" in namespaces
        assert "asset" in namespaces
        assert "research" in namespaces
    
    def test_nested_field(self):
        """Test parsing nested field access."""
        vars = parse_template_variables("{asset.stats.power}")
        
        assert len(vars) == 1
        assert vars[0].field == "stats.power"
    
    def test_no_variables(self):
        """Test template with no variables."""
        vars = parse_template_variables("Just plain text")
        assert len(vars) == 0
    
    def test_empty_template(self):
        """Test empty template."""
        vars = parse_template_variables("")
        assert len(vars) == 0
        
        vars = parse_template_variables(None)
        assert len(vars) == 0


class TestSubstituteTemplate:
    """Tests for template substitution."""
    
    def test_context_substitution(self):
        """Test substituting context variables."""
        result = substitute_template(
            "{context.style}, detailed art",
            context={"style": "pixel art"},
        )
        assert result == "pixel art, detailed art"
    
    def test_asset_substitution(self):
        """Test substituting asset variables."""
        result = substitute_template(
            "Create {asset.name} as a {asset.unit_class}",
            context={},
            asset={"name": "Archer", "unit_class": "ranged"},
        )
        assert result == "Create Archer as a ranged"
    
    def test_step_output_substitution(self):
        """Test substituting step output variables."""
        result = substitute_template(
            "Based on research: {research.output}",
            context={},
            step_outputs={"research": {"output": "Gothic themes"}},
        )
        assert result == "Based on research: Gothic themes"
    
    def test_ctx_alias(self):
        """Test that ctx is an alias for context."""
        result = substitute_template(
            "{ctx.style} art",
            context={"style": "watercolor"},
        )
        assert result == "watercolor art"
    
    def test_nested_context(self):
        """Test nested context access."""
        result = substitute_template(
            "{context.palette.primary}",
            context={"palette": {"primary": "blue"}},
        )
        assert result == "blue"
    
    def test_missing_optional_field(self):
        """Test that missing optional fields return empty string."""
        result = substitute_template(
            "Name: {asset.name}, Notes: {asset.notes}",
            context={},
            asset={"name": "Test"},  # notes is missing
        )
        assert result == "Name: Test, Notes: "
    
    def test_list_formatting(self):
        """Test that lists are formatted correctly."""
        result = substitute_template(
            "Colors: {context.colors}",
            context={"colors": ["red", "blue", "green"]},
        )
        assert result == "Colors: red, blue, green"
    
    def test_no_substitution_needed(self):
        """Test template with no variables."""
        result = substitute_template(
            "Just plain text",
            context={},
        )
        assert result == "Just plain text"
    
    def test_missing_context_raises(self):
        """Test that missing required context raises error."""
        with pytest.raises(TemplateError):
            substitute_template(
                "{context.missing_field}",
                context={},
            )


class TestSubstituteAll:
    """Tests for recursive template substitution."""
    
    def test_string(self):
        """Test substituting a string."""
        result = substitute_all(
            "{context.style}",
            context={"style": "pixel art"},
        )
        assert result == "pixel art"
    
    def test_dict(self):
        """Test substituting a dict."""
        result = substitute_all(
            {
                "prompt": "{context.style} character",
                "size": 512,
            },
            context={"style": "anime"},
        )
        assert result["prompt"] == "anime character"
        assert result["size"] == 512
    
    def test_list(self):
        """Test substituting a list."""
        result = substitute_all(
            ["{context.a}", "{context.b}", "static"],
            context={"a": "first", "b": "second"},
        )
        assert result == ["first", "second", "static"]
    
    def test_nested(self):
        """Test nested data structures."""
        result = substitute_all(
            {
                "outer": {
                    "inner": "{context.value}",
                },
                "list": ["{context.item}"],
            },
            context={"value": "deep", "item": "element"},
        )
        assert result["outer"]["inner"] == "deep"
        assert result["list"] == ["element"]


class TestValidateTemplate:
    """Tests for template validation."""
    
    def test_valid_template(self):
        """Test that valid template has no errors."""
        errors = validate_template(
            "{context.style}, {asset.name}",
            available_context={"style"},
            available_asset_fields={"name", "prompt"},
            available_step_outputs=set(),
        )
        assert len(errors) == 0
    
    def test_unknown_context(self):
        """Test that unknown context field is reported."""
        errors = validate_template(
            "{context.unknown}",
            available_context={"style"},
            available_asset_fields=set(),
            available_step_outputs=set(),
        )
        assert len(errors) == 1
        assert "unknown" in errors[0].lower()
    
    def test_unknown_asset_field(self):
        """Test that unknown asset field is reported."""
        errors = validate_template(
            "{asset.missing}",
            available_context=set(),
            available_asset_fields={"name"},
            available_step_outputs=set(),
        )
        assert len(errors) == 1
        assert "missing" in errors[0].lower()
    
    def test_unknown_step_output(self):
        """Test that unknown step output is reported."""
        errors = validate_template(
            "{unknown_step.output}",
            available_context=set(),
            available_asset_fields=set(),
            available_step_outputs={"research"},
        )
        assert len(errors) == 1
        assert "unknown_step" in errors[0].lower()
