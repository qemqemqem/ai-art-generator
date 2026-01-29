"""Tests for the expression evaluator."""

import pytest
from pipeline.expressions import (
    ExpressionEvaluator,
    ExpressionError,
    evaluate_condition,
    evaluate_expression,
)


class TestExpressionEvaluator:
    """Tests for the ExpressionEvaluator class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.evaluator = ExpressionEvaluator()
    
    def test_simple_comparison(self):
        """Test simple comparison expressions."""
        self.evaluator.set_context({"x": 5, "name": "test"})
        
        assert self.evaluator.evaluate("x > 3") is True
        assert self.evaluator.evaluate("x < 3") is False
        assert self.evaluator.evaluate("x == 5") is True
        assert self.evaluator.evaluate("name == 'test'") is True
    
    def test_boolean_logic(self):
        """Test boolean logic expressions."""
        self.evaluator.set_context({
            "rarity": "rare",
            "quality": 0.85,
        })
        
        assert self.evaluator.evaluate("rarity == 'rare' and quality > 0.8") is True
        assert self.evaluator.evaluate("rarity == 'common' or quality > 0.8") is True
        assert self.evaluator.evaluate("not (rarity == 'common')") is True
    
    def test_in_operator(self):
        """Test 'in' operator."""
        self.evaluator.set_context({
            "rarity": "rare",
            "allowed": ["rare", "mythic"],
        })
        
        assert self.evaluator.evaluate("rarity in ['rare', 'mythic']") is True
        assert self.evaluator.evaluate("rarity in ['common', 'uncommon']") is False
    
    def test_ternary_expression(self):
        """Test ternary (conditional) expressions."""
        self.evaluator.set_context({
            "rarity": "legendary",
        })
        
        result = self.evaluator.evaluate("4 if rarity == 'legendary' else 2")
        assert result == 4
        
        self.evaluator.update_context({"rarity": "common"})
        result = self.evaluator.evaluate("4 if rarity == 'legendary' else 2")
        assert result == 2
    
    def test_nested_dict_access(self):
        """Test accessing nested dictionary values."""
        self.evaluator.set_context({
            "asset": {
                "name": "Archer",
                "rarity": "rare",
                "stats": {
                    "power": 5,
                },
            },
        })
        
        assert self.evaluator.evaluate("asset_name == 'Archer'") is True
        assert self.evaluator.evaluate("asset_rarity == 'rare'") is True
        assert self.evaluator.evaluate("asset_stats_power > 3") is True
    
    def test_dot_notation_preprocessing(self):
        """Test that dot notation is converted to underscores."""
        self.evaluator.set_context({
            "asset": {
                "name": "Archer",
            },
        })
        
        # Should work with dot notation
        assert self.evaluator.evaluate("asset.name == 'Archer'") is True
    
    def test_math_operations(self):
        """Test arithmetic operations."""
        self.evaluator.set_context({"cost": 3})
        
        assert self.evaluator.evaluate("cost * 2") == 6
        assert self.evaluator.evaluate("cost + 1") == 4
        assert self.evaluator.evaluate("cost * 2 + 1") == 7
    
    def test_safe_functions(self):
        """Test allowed safe functions."""
        self.evaluator.set_context({
            "items": [1, 2, 3],
            "name": "  Test  ",
        })
        
        assert self.evaluator.evaluate("len(items)") == 3
        assert self.evaluator.evaluate("sum(items)") == 6
        assert self.evaluator.evaluate("max(items)") == 3
        assert self.evaluator.evaluate("min(items)") == 1
    
    def test_evaluate_bool(self):
        """Test evaluate_bool method."""
        self.evaluator.set_context({"x": 5})
        
        assert self.evaluator.evaluate_bool("x > 3") is True
        assert self.evaluator.evaluate_bool("x < 3") is False
        assert self.evaluator.evaluate_bool("", default=True) is True
        assert self.evaluator.evaluate_bool(None, default=False) is False
    
    def test_evaluate_int(self):
        """Test evaluate_int method."""
        self.evaluator.set_context({"x": 5})
        
        assert self.evaluator.evaluate_int("x * 2") == 10
        assert self.evaluator.evaluate_int("", default=0) == 0
    
    def test_invalid_syntax(self):
        """Test that invalid syntax raises ExpressionError."""
        self.evaluator.set_context({})
        
        with pytest.raises(ExpressionError):
            self.evaluator.evaluate("x ===== y")
    
    def test_undefined_variable(self):
        """Test that undefined variables raise ExpressionError."""
        self.evaluator.set_context({"x": 5})
        
        with pytest.raises(ExpressionError):
            self.evaluator.evaluate("undefined_var > 3")
    
    def test_context_update(self):
        """Test that context can be updated."""
        self.evaluator.set_context({"x": 5})
        assert self.evaluator.evaluate("x") == 5
        
        self.evaluator.update_context({"y": 10})
        assert self.evaluator.evaluate("x + y") == 15


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_evaluate_condition(self):
        """Test evaluate_condition function."""
        context = {"rarity": "rare", "quality": 0.9}
        
        assert evaluate_condition("rarity == 'rare'", context) is True
        assert evaluate_condition("quality < 0.5", context) is False
    
    def test_evaluate_expression(self):
        """Test evaluate_expression function."""
        context = {"x": 5, "y": 3}
        
        assert evaluate_expression("x + y", context) == 8
        assert evaluate_expression("x * y", context) == 15
