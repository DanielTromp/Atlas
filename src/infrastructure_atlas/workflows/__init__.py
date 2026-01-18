"""Workflow engine for the Atlas Agents Platform.

This module provides:
- WorkflowEngine: LangGraph-based workflow execution
- State management: TypedDict state definitions
- Node functions: Reusable workflow nodes
- Workflow definitions: Pre-built workflows (ESD Triage, etc.)
"""

from __future__ import annotations

__all__ = [
    "ESDTriageState",
    "WorkflowEngine",
    "WorkflowState",
]

# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    if name == "WorkflowEngine":
        from .engine import WorkflowEngine
        return WorkflowEngine
    elif name == "WorkflowState":
        from .state import WorkflowState
        return WorkflowState
    elif name == "ESDTriageState":
        from .state import ESDTriageState
        return ESDTriageState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
