"""Agent builders for the Infrastructure Atlas LangChain migration."""

# AI/LangChain functionality disabled - these imports require langchain dependencies
# from .base import AgentConfig, build_agent_executor, chat_history_from_messages
from .context import AgentContext
# from .domains import DOMAIN_SPECS
# from .registry import build_tool_registry
# from .router import RouterAgent, RouterDecision, build_router_agent
# from .utils import select_tools

# Stub function to allow tools.py to import without errors
def build_tool_registry():
    """Stub function - AI functionality disabled."""
    return {}

__all__ = [
    # "DOMAIN_SPECS",
    # "AgentConfig",
    "AgentContext",
    # "RouterAgent",
    # "RouterDecision",
    # "build_agent_executor",
    # "build_router_agent",
    "build_tool_registry",
    # "chat_history_from_messages",
    # "select_tools",
]
