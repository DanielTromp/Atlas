"""Worker agents for the Atlas Agents Platform.

These agents are specialized for specific tasks within workflows:
- TriageAgent: Categorize and assess incoming tickets
- EngineerAgent: Investigate and solve technical issues
- ReviewerAgent: Review and validate agent decisions
"""

from __future__ import annotations

__all__ = [
    "EngineerAgent",
    "ReviewerAgent",
    "TriageAgent",
]

# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    if name == "TriageAgent":
        from .triage import TriageAgent
        return TriageAgent
    elif name == "EngineerAgent":
        from .engineer import EngineerAgent
        return EngineerAgent
    elif name == "ReviewerAgent":
        from .reviewer import ReviewerAgent
        return ReviewerAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
