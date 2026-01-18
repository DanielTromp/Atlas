"""Agent builders for the Infrastructure Atlas.

This module provides:
- Legacy LangChain agent builders (AgentContext, build_tool_registry)
- New LangGraph-based workflow agents (BaseAgent, AgentConfig, workers)
"""

from .context import AgentContext
from .registry import build_tool_registry

__all__ = [
    # Legacy LangChain agents
    "AgentContext",
    "build_tool_registry",
    # LangGraph workflow agents
    "BaseAgent",
    "AgentConfig",
    "AgentMessage",
    "AgentResult",
]


# Lazy imports for new workflow agent components
def __getattr__(name: str):
    if name == "BaseAgent":
        from .workflow_agent import BaseAgent
        return BaseAgent
    elif name == "AgentConfig":
        from .workflow_agent import AgentConfig
        return AgentConfig
    elif name == "AgentMessage":
        from .workflow_agent import AgentMessage
        return AgentMessage
    elif name == "AgentResult":
        from .workflow_agent import AgentResult
        return AgentResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
