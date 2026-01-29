"""
Step Executors for Pipeline Execution.

Each step type has a corresponding executor that knows how to:
  - Execute the step's logic
  - Handle variations and selection
  - Save outputs to the appropriate location
  - Cache results for incremental runs
"""

from .base import StepExecutor, ExecutorContext, StepResult
from .registry import get_executor, register_executor

__all__ = [
    "StepExecutor",
    "ExecutorContext", 
    "StepResult",
    "get_executor",
    "register_executor",
]
