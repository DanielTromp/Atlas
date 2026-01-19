"""Playground runtime for direct agent testing.

The PlaygroundRuntime provides a simplified execution environment for testing
agents and skills without the full orchestration pipeline.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from infrastructure_atlas.agents.usage import UsageRecord, calculate_cost, create_usage_service
from infrastructure_atlas.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from infrastructure_atlas.agents.workflow_agent import BaseAgent
    from infrastructure_atlas.skills import SkillsRegistry

logger = get_logger(__name__)


class ChatEventType(str, Enum):
    """Types of events emitted during chat processing."""

    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_END = "message_end"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    STATE_UPDATE = "state_update"
    ERROR = "error"


@dataclass
class ChatEvent:
    """Event emitted during chat processing for streaming."""

    type: ChatEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SkillResult:
    """Result from executing a skill action."""

    success: bool
    result: Any
    duration_ms: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "result": self.result,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class AgentInfo:
    """Information about an available agent."""

    id: str
    name: str
    role: str
    description: str
    skills: list[str]
    default_model: str
    default_temperature: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "description": self.description,
            "skills": self.skills,
            "default_model": self.default_model,
            "default_temperature": self.default_temperature,
        }


# ============================================================================
# Model Configuration - Edit these to change default models
# ============================================================================
# Available models:
#   - claude-3-5-haiku-20241022  (fast, cost-effective)
#   - claude-haiku-4-5-20251001  (improved version of haiku)
#   - claude-sonnet-4-5-20250929 (balanced)
#   - claude-opus-4-20250514     (most capable)

MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-5-20251101",
}

# Default model for each agent type
AGENT_DEFAULTS = {
    "triage": {"model": MODELS["haiku"], "temperature": 0.3},
    "engineer": {"model": MODELS["sonnet"], "temperature": 0.5},
    "reviewer": {"model": MODELS["haiku"], "temperature": 0.2},
}

# ============================================================================
# Agent definitions with metadata
# ============================================================================
AVAILABLE_AGENTS: dict[str, AgentInfo] = {
    "triage": AgentInfo(
        id="triage",
        name="Triage Agent",
        role="Ticket categorization specialist",
        description="Analyzes incoming tickets, categorizes them, assesses complexity, and suggests assignees.",
        skills=["jira", "confluence"],
        default_model=AGENT_DEFAULTS["triage"]["model"],
        default_temperature=AGENT_DEFAULTS["triage"]["temperature"],
    ),
    "engineer": AgentInfo(
        id="engineer",
        name="Engineer Agent",
        role="Technical investigation specialist",
        description="Investigates technical issues using infrastructure tools, analyzes systems, and proposes solutions.",
        skills=["jira", "netbox", "zabbix", "vcenter", "commvault"],
        default_model=AGENT_DEFAULTS["engineer"]["model"],
        default_temperature=AGENT_DEFAULTS["engineer"]["temperature"],
    ),
    "reviewer": AgentInfo(
        id="reviewer",
        name="Reviewer Agent",
        role="Quality assurance specialist",
        description="Reviews agent decisions, validates solutions, and ensures quality before execution.",
        skills=["jira", "confluence"],
        default_model=AGENT_DEFAULTS["reviewer"]["model"],
        default_temperature=AGENT_DEFAULTS["reviewer"]["temperature"],
    ),
}


class PlaygroundSession:
    """Maintains state for a playground session.

    Sessions are ephemeral and track:
    - Active agent
    - Conversation history
    - Agent state
    - Configuration overrides
    - Token usage metrics
    """

    def __init__(
        self,
        session_id: str | None = None,
        agent_id: str = "triage",
        user_id: str | None = None,
        username: str | None = None,
        client: str | None = None,
    ):
        self.session_id = session_id or str(uuid.uuid4())
        self.agent_id = agent_id
        self.user_id = user_id
        self.username = username
        self.client = client or "web"  # Default to web
        self.messages: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {}
        self.config_override: dict[str, Any] = {}
        self.total_tokens = 0
        self.total_cost_usd = 0.0
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the conversation history."""
        self.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now(UTC).isoformat(),
                **kwargs,
            }
        )
        self.updated_at = datetime.now(UTC)

    def add_tokens(self, tokens: int, cost_usd: float = 0.0) -> None:
        """Track token usage."""
        self.total_tokens += tokens
        self.total_cost_usd += cost_usd
        self.updated_at = datetime.now(UTC)

    def update_state(self, updates: dict[str, Any]) -> None:
        """Update the session state."""
        self.state.update(updates)
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "username": self.username,
            "messages": self.messages,
            "state": self.state,
            "config_override": self.config_override,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def clear(self) -> None:
        """Clear the session conversation and state."""
        self.messages = []
        self.state = {}
        self.total_tokens = 0
        self.total_cost_usd = 0.0
        self.updated_at = datetime.now(UTC)


class PlaygroundRuntime:
    """Simplified runtime for direct agent testing.

    The PlaygroundRuntime bypasses the full orchestration pipeline and
    allows direct interaction with individual agents for testing purposes.

    Example usage:
        runtime = PlaygroundRuntime(skills_registry)

        # Direct chat with an agent
        async for event in runtime.chat("triage", "Analyze ticket ESD-123", session_id):
            print(event)

        # Execute a skill directly
        result = await runtime.execute_skill("jira", "get_issue", {"issue_key": "ESD-123"})
    """

    def __init__(
        self,
        skills_registry: SkillsRegistry,
        db_session: Session | None = None,
    ):
        """Initialize the playground runtime.

        Args:
            skills_registry: Registry of available skills
            db_session: Optional database session for persistence
        """
        self.skills = skills_registry
        self.db_session = db_session
        self._sessions: dict[str, PlaygroundSession] = {}
        self._agent_cache: dict[str, BaseAgent] = {}

        logger.info("PlaygroundRuntime initialized")

    def list_agents(self) -> list[AgentInfo]:
        """List all available agents.

        Returns:
            List of agent information objects
        """
        return list(AVAILABLE_AGENTS.values())

    def get_agent_info(self, agent_id: str) -> AgentInfo | None:
        """Get information about a specific agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Agent information or None if not found
        """
        return AVAILABLE_AGENTS.get(agent_id)

    def get_or_create_session(
        self,
        session_id: str | None = None,
        agent_id: str = "triage",
        user_id: str | None = None,
        username: str | None = None,
        client: str | None = None,
    ) -> PlaygroundSession:
        """Get an existing session or create a new one.

        Args:
            session_id: Optional session ID to retrieve
            agent_id: Agent ID for new sessions
            user_id: User ID for new sessions
            username: Username for new sessions
            client: Client identifier (web, telegram, slack, teams)

        Returns:
            PlaygroundSession instance
        """
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            # Update session with latest user info and client if provided
            if user_id and not session.user_id:
                session.user_id = user_id
            if username and not session.username:
                session.username = username
            if client and session.client == "web":
                session.client = client
            return session

        # Try to load from database if available
        if session_id and self.db_session:
            db_session = self._load_session_from_db(session_id)
            if db_session:
                # Update with latest info
                if user_id and not db_session.user_id:
                    db_session.user_id = user_id
                if username and not db_session.username:
                    db_session.username = username
                if client and db_session.client == "web":
                    db_session.client = client
                return db_session

        # Create new session
        session = PlaygroundSession(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            username=username,
            client=client,
        )
        self._sessions[session.session_id] = session

        # Persist to database if available
        if self.db_session:
            self._save_session_to_db(session)

        logger.info(
            f"Created playground session: {session.session_id}",
            extra={"agent_id": agent_id, "user_id": user_id},
        )

        return session

    def get_session(self, session_id: str) -> PlaygroundSession | None:
        """Get an existing session.

        Args:
            session_id: Session ID

        Returns:
            PlaygroundSession or None if not found
        """
        if session_id in self._sessions:
            return self._sessions[session_id]

        if self.db_session:
            return self._load_session_from_db(session_id)

        return None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session ID to delete

        Returns:
            True if deleted, False if not found
        """
        if session_id in self._sessions:
            del self._sessions[session_id]

        if self.db_session:
            self._delete_session_from_db(session_id)

        return True

    def _get_agent_instance(
        self,
        agent_id: str,
        config_override: dict[str, Any] | None = None,
    ) -> BaseAgent | None:
        """Get or create an agent instance.

        Args:
            agent_id: Agent identifier
            config_override: Optional configuration overrides

        Returns:
            Agent instance or None if not found
        """
        agent_info = AVAILABLE_AGENTS.get(agent_id)
        if not agent_info:
            logger.warning(f"Unknown agent: {agent_id}")
            return None

        # Import agent classes dynamically
        from infrastructure_atlas.agents.workers import EngineerAgent, ReviewerAgent, TriageAgent
        from infrastructure_atlas.agents.workflow_agent import AgentConfig

        agent_classes = {
            "triage": TriageAgent,
            "engineer": EngineerAgent,
            "reviewer": ReviewerAgent,
        }

        agent_class = agent_classes.get(agent_id)
        if not agent_class:
            logger.warning(f"No implementation for agent: {agent_id}")
            return None

        # Build config with overrides
        model = config_override.get("model", agent_info.default_model) if config_override else agent_info.default_model
        temperature = (
            config_override.get("temperature", agent_info.default_temperature)
            if config_override
            else agent_info.default_temperature
        )
        max_tokens = config_override.get("max_tokens", 4096) if config_override else 4096

        # Filter skills if specified
        skills = agent_info.skills
        if config_override and "skills" in config_override:
            enabled_skills = set(config_override["skills"])
            skills = [s for s in skills if s in enabled_skills]

        config = AgentConfig(
            name=agent_info.name,
            role=agent_info.role,
            prompt_file=f"{agent_id}.md",
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=skills,
        )

        return agent_class(config=config, skills_registry=self.skills)

    async def chat(  # noqa: PLR0913
        self,
        agent_id: str,
        message: str,
        session_id: str | None = None,
        state: dict[str, Any] | None = None,
        config_override: dict[str, Any] | None = None,
        stream: bool = True,
        user_id: str | None = None,
        username: str | None = None,
        client: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Send a message directly to an agent.

        Args:
            agent_id: Agent identifier
            message: User message
            session_id: Optional session ID for context
            state: Optional state to inject
            config_override: Optional configuration overrides
            stream: Whether to stream the response
            user_id: User ID for usage tracking
            username: Username for usage tracking
            client: Client identifier (web, telegram, slack, teams)

        Yields:
            ChatEvent objects for real-time updates
        """
        start_time = time.perf_counter()

        # Get or create session
        session = self.get_or_create_session(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            username=username,
            client=client,
        )

        # Apply config override to session
        if config_override:
            session.config_override = config_override

        # Inject state if provided
        if state:
            session.update_state(state)

        # Add user message to history
        session.add_message("user", message)

        yield ChatEvent(
            type=ChatEventType.MESSAGE_START,
            data={"session_id": session.session_id, "agent_id": agent_id},
        )

        try:
            # Get agent instance
            agent = self._get_agent_instance(agent_id, session.config_override)
            if not agent:
                yield ChatEvent(
                    type=ChatEventType.ERROR,
                    data={"error": f"Agent '{agent_id}' not found"},
                )
                return

            # Use the agent's LLM directly for chat
            llm = self._create_llm_with_overrides(agent, session.config_override)
            tools = agent._tools if hasattr(agent, "_tools") else []

            if tools:
                llm = llm.bind_tools(tools)

            # Build messages for LLM
            langchain_messages = [
                SystemMessage(content=agent._system_prompt),
                *[
                    HumanMessage(content=m["content"]) if m["role"] == "user" else AIMessage(content=m["content"])
                    for m in session.messages[:-1]  # Exclude last message, we'll add it fresh
                ],
                HumanMessage(content=message),
            ]

            # Execute with tool loop
            response_content = ""
            input_tokens = 0
            output_tokens = 0
            tool_calls_log: list[dict[str, Any]] = []
            max_iterations = 10
            model = session.config_override.get("model", agent.config.model) if session.config_override else agent.config.model

            for _ in range(max_iterations):
                response = llm.invoke(langchain_messages)

                # Track tokens separately
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    input_tokens += response.usage_metadata.get("input_tokens", 0)
                    output_tokens += response.usage_metadata.get("output_tokens", 0)

                # Check for tool calls
                if hasattr(response, "tool_calls") and response.tool_calls:
                    langchain_messages.append(response)

                    for tool_call in response.tool_calls:
                        tool_name = tool_call["name"]
                        tool_args = tool_call.get("args", {})

                        yield ChatEvent(
                            type=ChatEventType.TOOL_START,
                            data={"tool": tool_name, "args": tool_args},
                        )

                        tool_start = time.perf_counter()
                        tool_result = self._execute_agent_tool(agent, tool_name, tool_args)
                        tool_duration = int((time.perf_counter() - tool_start) * 1000)

                        # Log tool call for usage tracking
                        tool_calls_log.append({
                            "name": tool_name,
                            "args": tool_args,
                            "duration_ms": tool_duration,
                        })

                        yield ChatEvent(
                            type=ChatEventType.TOOL_END,
                            data={
                                "tool": tool_name,
                                "result": str(tool_result)[:500],  # Truncate
                                "duration_ms": tool_duration,
                            },
                        )

                        langchain_messages.append(
                            ToolMessage(
                                content=str(tool_result),
                                tool_call_id=tool_call["id"],
                            )
                        )
                else:
                    # No tool calls, we have the final response
                    response_content = response.content if isinstance(response.content, str) else str(response.content)
                    break

            # Calculate accurate cost using pricing table
            total_tokens = input_tokens + output_tokens
            cost_usd = calculate_cost(model, input_tokens, output_tokens)

            # Update session
            session.add_message("assistant", response_content)
            session.add_tokens(total_tokens, cost_usd)

            # Save to DB if available
            if self.db_session:
                self._save_session_to_db(session)

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            yield ChatEvent(
                type=ChatEventType.MESSAGE_DELTA,
                data={"content": response_content},
            )

            yield ChatEvent(
                type=ChatEventType.MESSAGE_END,
                data={
                    "tokens": total_tokens,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                    "duration_ms": duration_ms,
                },
            )

            # Record usage to database
            if self.db_session:
                self._record_usage(
                    session=session,
                    model=model,
                    user_message=message,
                    assistant_message=response_content,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    tool_calls=tool_calls_log if tool_calls_log else None,
                    duration_ms=duration_ms,
                )

            logger.info(
                "Playground chat completed",
                extra={
                    "agent_id": agent_id,
                    "session_id": session.session_id,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                    "duration_ms": duration_ms,
                },
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            error_msg = str(e)
            logger.error(f"Playground chat error: {error_msg}", exc_info=True)

            # Record error usage if we have a session
            if self.db_session and session:
                self._record_usage(
                    session=session,
                    model=config_override.get("model", AGENT_DEFAULTS.get(agent_id, {}).get("model", "unknown")) if config_override else AGENT_DEFAULTS.get(agent_id, {}).get("model", "unknown"),
                    user_message=message,
                    assistant_message=None,
                    input_tokens=0,
                    output_tokens=0,
                    tool_calls=None,
                    duration_ms=duration_ms,
                    error=error_msg,
                )

            yield ChatEvent(
                type=ChatEventType.ERROR,
                data={"error": error_msg},
            )

    async def execute_skill(
        self,
        skill_name: str,
        action_name: str,
        params: dict[str, Any],
    ) -> SkillResult:
        """Execute a skill action directly.

        Args:
            skill_name: Name of the skill
            action_name: Name of the action to execute
            params: Parameters for the action

        Returns:
            SkillResult with execution details
        """
        start_time = time.perf_counter()

        skill = self.skills.get(skill_name)
        if not skill:
            return SkillResult(
                success=False,
                result=None,
                duration_ms=0,
                error=f"Skill '{skill_name}' not found",
            )

        try:
            result = skill.execute(action_name, params)
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logger.info(
                f"Skill executed: {skill_name}.{action_name}",
                extra={"duration_ms": duration_ms},
            )

            return SkillResult(
                success=True,
                result=result,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(f"Skill execution error: {e!s}")

            return SkillResult(
                success=False,
                result=None,
                duration_ms=duration_ms,
                error=str(e),
            )

    def _build_chat_context(self, session: PlaygroundSession) -> str:
        """Build context string from session state."""
        parts = []

        if session.state:
            parts.append(f"Current state:\n{session.state}")

        if session.messages:
            parts.append(f"Conversation has {len(session.messages)} messages")

        return "\n\n".join(parts) if parts else "No context"

    def _create_llm_with_overrides(
        self,
        agent: BaseAgent,
        config_override: dict[str, Any] | None,
    ) -> ChatAnthropic:
        """Create LLM instance with config overrides."""
        model = agent.config.model
        temperature = agent.config.temperature
        max_tokens = agent.config.max_tokens

        if config_override:
            model = config_override.get("model", model)
            temperature = config_override.get("temperature", temperature)
            max_tokens = config_override.get("max_tokens", max_tokens)

        return ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _execute_agent_tool(
        self,
        agent: BaseAgent,
        tool_name: str,
        args: dict[str, Any],
    ) -> Any:
        """Execute a tool from an agent's toolset."""
        for tool in agent._tools:
            if tool.name == tool_name:
                return tool.invoke(args)
        return f"Tool '{tool_name}' not found"

    def _record_usage(  # noqa: PLR0913
        self,
        session: PlaygroundSession,
        model: str,
        user_message: str,
        assistant_message: str | None,
        input_tokens: int,
        output_tokens: int,
        tool_calls: list[dict[str, Any]] | None,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        """Record usage to the database.

        Args:
            session: The playground session
            model: Model used for the request
            user_message: The user's message
            assistant_message: The assistant's response (or None on error)
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            tool_calls: List of tool calls made
            duration_ms: Duration in milliseconds
            error: Error message if any
        """
        try:
            usage_service = create_usage_service(session=self.db_session)
            record = UsageRecord(
                session_id=session.session_id,
                agent_id=session.agent_id,
                model=model,
                user_message=user_message,
                assistant_message=assistant_message,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tool_calls=tool_calls,
                duration_ms=duration_ms,
                error=error,
                user_id=session.user_id,
                username=session.username,
                client=session.client,
            )
            usage_service.record(record)
        except Exception as e:
            logger.error(f"Failed to record usage: {e!s}", exc_info=True)

    def _load_session_from_db(self, session_id: str) -> PlaygroundSession | None:
        """Load a session from the database."""
        if not self.db_session:
            return None

        from infrastructure_atlas.db.models import PlaygroundSession as DBSession

        db_session = self.db_session.query(DBSession).filter_by(id=session_id).first()
        if not db_session:
            return None

        session = PlaygroundSession(
            session_id=db_session.id,
            agent_id=db_session.agent_id,
            user_id=db_session.user_id,
            client=db_session.client,
        )
        session.messages = db_session.messages or []
        session.state = db_session.state or {}
        session.config_override = db_session.config_override or {}
        session.total_tokens = db_session.total_tokens or 0
        session.total_cost_usd = db_session.total_cost_usd or 0.0
        session.created_at = db_session.created_at
        session.updated_at = db_session.updated_at

        self._sessions[session_id] = session
        return session

    def _save_session_to_db(self, session: PlaygroundSession) -> None:
        """Save a session to the database (MongoDB or SQLite)."""
        import os
        from datetime import UTC, datetime

        backend = os.getenv("ATLAS_STORAGE_BACKEND", "sqlite").lower()

        if backend == "mongodb":
            try:
                from infrastructure_atlas.infrastructure.mongodb.client import get_mongodb_client

                db = get_mongodb_client().atlas
                collection = db["playground_sessions"]

                doc = {
                    "_id": session.session_id,
                    "agent_id": session.agent_id,
                    "user_id": session.user_id,
                    "client": session.client,
                    "messages": session.messages,
                    "state": session.state,
                    "config_override": session.config_override,
                    "total_tokens": session.total_tokens,
                    "total_cost_usd": session.total_cost_usd,
                    "updated_at": datetime.now(UTC),
                }

                collection.replace_one({"_id": session.session_id}, doc, upsert=True)
            except Exception as e:
                logger.error(f"Failed to save session to MongoDB: {e!s}")
        else:
            # SQLite fallback
            if not self.db_session:
                return

            try:
                from infrastructure_atlas.db.models import PlaygroundSession as DBSession

                db_session = self.db_session.query(DBSession).filter_by(id=session.session_id).first()

                if db_session:
                    # Update existing
                    db_session.agent_id = session.agent_id
                    db_session.user_id = session.user_id
                    db_session.client = session.client
                    db_session.messages = session.messages
                    db_session.state = session.state
                    db_session.config_override = session.config_override
                    db_session.total_tokens = session.total_tokens
                    db_session.total_cost_usd = session.total_cost_usd
                else:
                    # Create new
                    db_session = DBSession(
                        id=session.session_id,
                        agent_id=session.agent_id,
                        user_id=session.user_id,
                        client=session.client,
                        messages=session.messages,
                        state=session.state,
                        config_override=session.config_override,
                        total_tokens=session.total_tokens,
                        total_cost_usd=session.total_cost_usd,
                    )
                    self.db_session.add(db_session)

                self.db_session.commit()
            except Exception as e:
                logger.error(f"Failed to save session to DB: {e!s}")
                self.db_session.rollback()

    def _delete_session_from_db(self, session_id: str) -> None:
        """Delete a session from the database (MongoDB or SQLite)."""
        import os

        backend = os.getenv("ATLAS_STORAGE_BACKEND", "sqlite").lower()

        if backend == "mongodb":
            try:
                from infrastructure_atlas.infrastructure.mongodb.client import get_mongodb_client

                db = get_mongodb_client().atlas
                collection = db["playground_sessions"]
                collection.delete_one({"_id": session_id})
            except Exception as e:
                logger.error(f"Failed to delete session from MongoDB: {e!s}")
        else:
            # SQLite fallback
            if not self.db_session:
                return

            from infrastructure_atlas.db.models import PlaygroundSession as DBSession

            self.db_session.query(DBSession).filter_by(id=session_id).delete()
            self.db_session.commit()


# Factory function for dependency injection
def get_playground_runtime(
    skills_registry: SkillsRegistry,
    db_session: Session | None = None,
) -> PlaygroundRuntime:
    """Get a PlaygroundRuntime instance.

    Args:
        skills_registry: Registry of available skills
        db_session: Optional database session

    Returns:
        PlaygroundRuntime instance
    """
    return PlaygroundRuntime(skills_registry, db_session)
