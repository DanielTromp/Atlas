"""Base helpers for constructing LangChain agents."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from textwrap import dedent

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool

from .context import AgentContext

__all__ = [
    "AgentConfig",
    "build_agent_executor",
    "chat_history_from_messages",
]


@dataclass(frozen=True)
class AgentConfig:
    """Configuration required to build an AgentExecutor."""

    name: str
    goal: str
    instructions: str
    tools: Sequence[BaseTool]
    max_iterations: int = 4


def build_agent_executor(
    llm: BaseLanguageModel,
    config: AgentConfig,
    context: AgentContext,
) -> AgentExecutor:
    """Create a deterministic agent with shared prompting conventions."""

    system_prompt = dedent(
        f"""
        You are the {config.name}. Stay focused on your domain goal: {config.goal}.
        Use the provided tools conservatively. When the user prompt is fully satisfied by context, answer directly.
        Call at most one tool at a time and chain only when essential.
        Ask for clarification once at most when required parameters are missing.
        Dates must be absolute and formatted for Europe/Amsterdam with explicit CET/CEST suffix.
        Keep answers short, factual and oriented to operational tasks.

        Shared context:
        {context.as_prompt_fragment()}

        Domain guidance:
        {config.instructions.strip()}
        """
    ).strip()

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    agent = create_tool_calling_agent(llm, list(config.tools), prompt)
    executor = AgentExecutor(
        agent=agent,
        tools=list(config.tools),
        verbose=False,
        max_iterations=config.max_iterations,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )
    return executor


def chat_history_from_messages(messages: Sequence[dict[str, str]]) -> list[BaseMessage]:
    """Convert stored chat history into LangChain message instances."""

    # Deferred import to avoid making langchain an unconditional import in call sites.
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    history: list[BaseMessage] = []
    for message in messages:
        role = (message.get("role") or "").strip().lower()
        content = str(message.get("content") or "")
        if role == "user":
            history.append(HumanMessage(content=content))
        elif role == "assistant":
            history.append(AIMessage(content=content))
        elif role == "system":
            history.append(SystemMessage(content=content))
    return history
