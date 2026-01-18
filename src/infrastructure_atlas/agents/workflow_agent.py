"""Base agent class for LangGraph-based workflow agents.

This module provides the foundation for creating agents that work within
LangGraph workflows with human-in-the-loop capabilities.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills import SkillsRegistry

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentConfig:
    """Configuration for a workflow agent."""

    name: str
    role: str
    prompt_file: str
    model: str = "claude-sonnet-4-5-20250929"
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: list[str] = field(default_factory=list)
    provider: Literal["anthropic", "azure_openai"] = "anthropic"


@dataclass
class AgentMessage:
    """A message in an agent's conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None  # Tool name for tool messages

    def to_langchain(self) -> BaseMessage:
        """Convert to a LangChain message."""
        if self.role == "system":
            return SystemMessage(content=self.content)
        elif self.role == "user":
            return HumanMessage(content=self.content)
        elif self.role == "assistant":
            return AIMessage(content=self.content)
        else:
            return HumanMessage(content=f"[Tool Result: {self.name}] {self.content}")


@dataclass
class AgentResult:
    """Result from an agent's process method."""

    output: dict[str, Any]
    messages: list[AgentMessage] = field(default_factory=list)
    tokens_used: int = 0
    duration_ms: int = 0
    error: str | None = None


class BaseAgent(ABC):
    """Abstract base class for workflow agents.

    Agents are specialized components that:
    - Process workflow state
    - Use LLM for reasoning
    - Execute tools/skills
    - Return updated state

    Example usage:
        class TriageAgent(BaseAgent):
            def process(self, state: dict) -> dict:
                # Analyze ticket and categorize
                result = self.think(
                    context=f"Ticket: {state['ticket']}",
                    question="What category is this ticket?"
                )
                state['category'] = result
                return state
    """

    def __init__(
        self,
        config: AgentConfig,
        skills_registry: SkillsRegistry | None = None,
    ):
        self.config = config
        self.skills_registry = skills_registry
        self._system_prompt = self._load_system_prompt()
        self._llm = self._create_llm()
        self._tools: list[BaseTool] = []

        # Load tools from skills registry
        if skills_registry and config.tools:
            self._tools = self._load_tools_from_skills(config.tools)

        logger.info(
            f"Initialized agent: {config.name}",
            extra={
                "event": "agent_init",
                "agent_name": config.name,
                "model": config.model,
                "tool_count": len(self._tools),
            },
        )

    def _load_system_prompt(self) -> str:
        """Load the system prompt from the markdown file."""
        prompt_path = Path(__file__).parent / "prompts" / self.config.prompt_file

        if not prompt_path.exists():
            logger.warning(f"Prompt file not found: {prompt_path}")
            return f"You are the {self.config.name}, a {self.config.role}."

        return prompt_path.read_text(encoding="utf-8")

    def _create_llm(self) -> ChatAnthropic:
        """Create the LLM instance."""
        return ChatAnthropic(
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def _load_tools_from_skills(self, tool_names: list[str]) -> list[BaseTool]:
        """Load tools from the skills registry."""
        if not self.skills_registry:
            return []

        tools = []
        for name in tool_names:
            skill = self.skills_registry.get(name)
            if skill:
                tools.extend(skill.get_langchain_tools())
            else:
                logger.warning(f"Skill not found: {name}")

        return tools

    @abstractmethod
    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Process the workflow state and return updated state.

        This is the main entry point for the agent within a workflow.

        Args:
            state: The current workflow state

        Returns:
            Updated workflow state
        """
        ...

    def think(self, context: str, question: str) -> str:
        """Use the LLM for simple reasoning without tools.

        Args:
            context: Context information for the question
            question: The question to answer

        Returns:
            The LLM's response
        """
        start_time = time.perf_counter()

        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}"),
        ]

        try:
            response = self._llm.invoke(messages)
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logger.debug(
                "Agent think completed",
                extra={
                    "event": "agent_think",
                    "agent_name": self.config.name,
                    "duration_ms": duration_ms,
                },
            )

            return response.content if isinstance(response.content, str) else str(response.content)

        except Exception as e:
            logger.error(f"Agent think failed: {e!s}", extra={"agent_name": self.config.name})
            raise

    def execute_with_tools(
        self,
        state: dict[str, Any],
        task: str,
        max_iterations: int = 10,
    ) -> AgentResult:
        """Execute a task using available tools.

        This method implements a ReAct-style loop:
        1. Think about the task
        2. Choose and execute a tool
        3. Observe the result
        4. Repeat until done or max iterations

        Args:
            state: The current workflow state
            task: The task to accomplish
            max_iterations: Maximum tool-calling iterations

        Returns:
            AgentResult with output and execution details
        """
        start_time = time.perf_counter()
        messages: list[AgentMessage] = []
        total_tokens = 0

        # Build initial context from state
        context = self._build_context_from_state(state)

        messages.append(AgentMessage(role="system", content=self._system_prompt))
        messages.append(AgentMessage(role="user", content=f"Context:\n{context}\n\nTask: {task}"))

        langchain_messages = [msg.to_langchain() for msg in messages]

        # Bind tools to LLM if available
        llm = self._llm
        if self._tools:
            llm = self._llm.bind_tools(self._tools)

        for iteration in range(max_iterations):
            try:
                response = llm.invoke(langchain_messages)

                # Track token usage if available
                if hasattr(response, "usage_metadata"):
                    metadata = response.usage_metadata or {}
                    total_tokens += metadata.get("total_tokens", 0)

                # Check for tool calls
                if hasattr(response, "tool_calls") and response.tool_calls:
                    # Record assistant message with tool calls
                    messages.append(
                        AgentMessage(
                            role="assistant",
                            content=response.content if isinstance(response.content, str) else "",
                            tool_calls=response.tool_calls,
                        )
                    )
                    langchain_messages.append(response)

                    # Execute each tool call
                    for tool_call in response.tool_calls:
                        tool_result = self._execute_tool(
                            tool_call["name"],
                            tool_call.get("args", {}),
                        )

                        # Record tool result
                        messages.append(
                            AgentMessage(
                                role="tool",
                                content=str(tool_result),
                                tool_call_id=tool_call["id"],
                                name=tool_call["name"],
                            )
                        )

                        # Add tool result to conversation
                        from langchain_core.messages import ToolMessage

                        langchain_messages.append(
                            ToolMessage(
                                content=str(tool_result),
                                tool_call_id=tool_call["id"],
                            )
                        )
                else:
                    # No tool calls - we're done
                    final_content = response.content if isinstance(response.content, str) else str(response.content)
                    messages.append(AgentMessage(role="assistant", content=final_content))

                    duration_ms = int((time.perf_counter() - start_time) * 1000)

                    logger.info(
                        f"Agent completed task in {iteration + 1} iterations",
                        extra={
                            "event": "agent_execute_complete",
                            "agent_name": self.config.name,
                            "iterations": iteration + 1,
                            "duration_ms": duration_ms,
                            "tokens_used": total_tokens,
                        },
                    )

                    return AgentResult(
                        output={"response": final_content},
                        messages=messages,
                        tokens_used=total_tokens,
                        duration_ms=duration_ms,
                    )

            except Exception as e:
                logger.error(f"Agent execution error: {e!s}", extra={"agent_name": self.config.name})
                return AgentResult(
                    output={},
                    messages=messages,
                    tokens_used=total_tokens,
                    duration_ms=int((time.perf_counter() - start_time) * 1000),
                    error=str(e),
                )

        # Max iterations reached
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return AgentResult(
            output={"response": "Max iterations reached without completion"},
            messages=messages,
            tokens_used=total_tokens,
            duration_ms=duration_ms,
            error="Max iterations reached",
        )

    def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Execute a tool by name."""
        for tool in self._tools:
            if tool.name == tool_name:
                logger.debug(f"Executing tool: {tool_name}", extra={"args": args})
                return tool.invoke(args)

        logger.warning(f"Tool not found: {tool_name}")
        return f"Error: Tool '{tool_name}' not found"

    def _build_context_from_state(self, state: dict[str, Any]) -> str:
        """Build a context string from workflow state.

        Override this in subclasses for custom context formatting.
        """
        context_parts = []

        # Extract key state items
        if "ticket" in state:
            context_parts.append(f"Ticket: {state['ticket']}")
        if "ticket_id" in state:
            context_parts.append(f"Ticket ID: {state['ticket_id']}")
        if "investigation" in state:
            context_parts.append(f"Investigation: {state['investigation']}")
        if "related_systems" in state:
            context_parts.append(f"Related Systems: {state['related_systems']}")

        return "\n\n".join(context_parts) if context_parts else "No context available"
