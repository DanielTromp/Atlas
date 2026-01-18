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
    # Playground components
    "PlaygroundRuntime",
    "PlaygroundSession",
    "ChatEvent",
    "ChatEventType",
    "SkillResult",
    "get_playground_runtime",
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
    elif name == "PlaygroundRuntime":
        from .playground import PlaygroundRuntime
        return PlaygroundRuntime
    elif name == "PlaygroundSession":
        from .playground import PlaygroundSession
        return PlaygroundSession
    elif name == "ChatEvent":
        from .playground import ChatEvent
        return ChatEvent
    elif name == "ChatEventType":
        from .playground import ChatEventType
        return ChatEventType
    elif name == "SkillResult":
        from .playground import SkillResult
        return SkillResult
    elif name == "get_playground_runtime":
        from .playground import get_playground_runtime
        return get_playground_runtime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
