"""
Expression Evaluator for Pipeline Conditions and Dynamic Values.

Uses simpleeval for safe expression evaluation. This module provides
a sandboxed Python-like expression language for:
  - Conditions: when: "rarity == 'legendary'"
  - Dynamic values: variations: "4 if rarity == 'legendary' else 2"
  - Comparisons: quality >= 0.8
  - Boolean logic: rarity in ['rare', 'mythic'] and quality > 0.7

Security: simpleeval prevents arbitrary code execution by limiting
available operations and blocking imports/function calls.
"""

from typing import Any

from simpleeval import EvalWithCompoundTypes, FeatureNotAvailable


class ExpressionError(Exception):
    """Error evaluating an expression."""
    pass


class ExpressionEvaluator:
    """
    Safe expression evaluator using simpleeval.
    
    Provides a Python-like expression language with controlled access
    to variables and limited operations.
    
    Example:
        evaluator = ExpressionEvaluator()
        evaluator.set_context({
            "asset": {"name": "Archer", "rarity": "rare"},
            "quality": 0.85,
        })
        
        # Evaluate conditions
        evaluator.evaluate("asset.rarity == 'rare'")  # True
        evaluator.evaluate("quality >= 0.8")          # True
        
        # Dynamic values
        evaluator.evaluate("4 if asset.rarity == 'legendary' else 2")  # 2
    """
    
    # Allowed operators and functions
    SAFE_FUNCTIONS = {
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "sum": sum,
        "any": any,
        "all": all,
        "sorted": sorted,
        "reversed": lambda x: list(reversed(x)),
        "lower": lambda s: s.lower() if isinstance(s, str) else s,
        "upper": lambda s: s.upper() if isinstance(s, str) else s,
        "strip": lambda s: s.strip() if isinstance(s, str) else s,
    }
    
    def __init__(self):
        self._context: dict[str, Any] = {}
        self._evaluator = EvalWithCompoundTypes(
            names=self._context,
            functions=self.SAFE_FUNCTIONS,
        )
    
    def set_context(self, context: dict[str, Any]) -> None:
        """
        Set the evaluation context.
        
        Context is a dict of variables accessible in expressions.
        Nested dicts are accessible via dot notation.
        
        Args:
            context: Variables to make available
        """
        self._context.clear()
        self._flatten_context(context, self._context)
        self._evaluator.names = self._context
    
    def update_context(self, updates: dict[str, Any]) -> None:
        """
        Update the evaluation context with new values.
        
        Args:
            updates: Variables to add or update
        """
        self._flatten_context(updates, self._context)
        self._evaluator.names = self._context
    
    def _flatten_context(self, source: dict[str, Any], target: dict[str, Any], prefix: str = "") -> None:
        """
        Flatten nested dicts for simpleeval compatibility.
        
        simpleeval doesn't handle nested attribute access well,
        so we flatten {"asset": {"name": "X"}} to {"asset": {...}, "asset_name": "X"}
        but also keep the original dict for `in` checks.
        """
        for key, value in source.items():
            full_key = f"{prefix}{key}" if prefix else key
            target[full_key] = value
            
            # Also flatten nested dicts
            if isinstance(value, dict):
                # Keep the original dict for operations like `key in dict`
                self._flatten_context(value, target, f"{full_key}_")
    
    def evaluate(self, expression: str) -> Any:
        """
        Evaluate an expression in the current context.
        
        Args:
            expression: The expression to evaluate
            
        Returns:
            The result of the expression
            
        Raises:
            ExpressionError: If the expression is invalid or unsafe
        """
        if not expression or not expression.strip():
            return None
        
        # Pre-process: convert dot notation to underscore for nested access
        # "asset.name" -> "asset_name"
        processed = self._preprocess_expression(expression)
        
        try:
            return self._evaluator.eval(processed)
        except FeatureNotAvailable as e:
            raise ExpressionError(f"Unsafe operation in expression: {e}")
        except SyntaxError as e:
            raise ExpressionError(f"Invalid syntax in expression '{expression}': {e}")
        except NameError as e:
            raise ExpressionError(f"Unknown variable in expression '{expression}': {e}")
        except Exception as e:
            raise ExpressionError(f"Error evaluating '{expression}': {e}")
    
    def _preprocess_expression(self, expression: str) -> str:
        """
        Preprocess an expression to handle dot notation.
        
        Converts "asset.name" to "asset_name" for simpleeval compatibility,
        but preserves string literals and method calls.
        """
        import re
        
        result = []
        i = 0
        in_string = False
        string_char = None
        
        while i < len(expression):
            char = expression[i]
            
            # Track string state
            if char in ('"', "'") and (i == 0 or expression[i-1] != '\\'):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
                result.append(char)
                i += 1
                continue
            
            # If in string, pass through unchanged
            if in_string:
                result.append(char)
                i += 1
                continue
            
            # Convert dot notation outside strings
            if char == '.':
                # Check if this is a method call (followed by identifier then '(')
                # or a number (preceded by digit)
                if i > 0 and expression[i-1].isdigit():
                    # Part of a number like 0.5
                    result.append(char)
                else:
                    # Convert to underscore for attribute access
                    result.append('_')
                i += 1
                continue
            
            result.append(char)
            i += 1
        
        return ''.join(result)
    
    def evaluate_bool(self, expression: str, default: bool = False) -> bool:
        """
        Evaluate an expression as a boolean.
        
        Args:
            expression: The expression to evaluate
            default: Value to return if expression is empty/None
            
        Returns:
            Boolean result of the expression
        """
        if not expression:
            return default
        
        result = self.evaluate(expression)
        return bool(result)
    
    def evaluate_int(self, expression: str, default: int = 0) -> int:
        """
        Evaluate an expression as an integer.
        
        Args:
            expression: The expression to evaluate
            default: Value to return if expression is empty/None
            
        Returns:
            Integer result of the expression
        """
        if not expression:
            return default
        
        result = self.evaluate(expression)
        try:
            return int(result)
        except (ValueError, TypeError):
            raise ExpressionError(f"Expression '{expression}' did not evaluate to an integer: {result}")


def evaluate_condition(expression: str, context: dict[str, Any]) -> bool:
    """
    Convenience function to evaluate a condition.
    
    Args:
        expression: The condition expression
        context: Variables for evaluation
        
    Returns:
        Boolean result
    """
    evaluator = ExpressionEvaluator()
    evaluator.set_context(context)
    return evaluator.evaluate_bool(expression)


def evaluate_expression(expression: str, context: dict[str, Any]) -> Any:
    """
    Convenience function to evaluate an expression.
    
    Args:
        expression: The expression to evaluate
        context: Variables for evaluation
        
    Returns:
        Result of the expression
    """
    evaluator = ExpressionEvaluator()
    evaluator.set_context(context)
    return evaluator.evaluate(expression)
