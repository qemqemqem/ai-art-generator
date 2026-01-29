"""
Step Executor Registry.

Provides a registry for step executors, allowing dynamic dispatch
based on step type.
"""

from typing import Type

from .base import StepExecutor


# Global registry of step executors
_EXECUTORS: dict[str, Type[StepExecutor]] = {}


def register_executor(step_type: str):
    """
    Decorator to register a step executor.
    
    Usage:
        @register_executor("research")
        class ResearchExecutor(StepExecutor):
            ...
    """
    def decorator(cls: Type[StepExecutor]):
        _EXECUTORS[step_type] = cls
        cls.step_type = step_type
        return cls
    return decorator


def get_executor(step_type: str) -> StepExecutor:
    """
    Get an executor instance for a step type.
    
    Args:
        step_type: The step type (e.g., "research", "generate_image")
        
    Returns:
        An executor instance
        
    Raises:
        ValueError: If no executor is registered for the type
    """
    if step_type not in _EXECUTORS:
        raise ValueError(f"No executor registered for step type: {step_type}")
    
    return _EXECUTORS[step_type]()


def list_executors() -> list[str]:
    """
    List all registered step types.
    
    Returns:
        List of registered step type names
    """
    return list(_EXECUTORS.keys())


def is_registered(step_type: str) -> bool:
    """
    Check if an executor is registered for a step type.
    
    Args:
        step_type: The step type to check
        
    Returns:
        True if registered
    """
    return step_type in _EXECUTORS
