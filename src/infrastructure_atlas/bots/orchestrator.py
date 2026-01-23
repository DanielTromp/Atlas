"""Bot orchestrator for routing messages to agents.

The BotOrchestrator serves as the central hub for processing bot messages:
1. Verifies user authorization (linked platform account)
2. Parses agent mentions (@agent_name) or routes to default agent
3. Routes messages to the PlaygroundRuntime
4. Formats responses for the target platform
5. Logs all interactions for visibility
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from infrastructure_atlas.agents.playground import (
    AVAILABLE_AGENTS,
    ChatEventType,
    PlaygroundRuntime,
)
from infrastructure_atlas.bots.formatters import FormattedMessage, FormatterRegistry
from infrastructure_atlas.bots.linking import UserLinkingService
from infrastructure_atlas.db.models import BotConversation, BotMessage, BotPlatformAccount
from infrastructure_atlas.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from infrastructure_atlas.skills import SkillsRegistry

logger = get_logger(__name__)


class BotResponseType(str, Enum):
    """Types of bot response chunks."""

    TEXT = "text"
    TOOL_CALL = "tool_call"
    TYPING = "typing"
    ERROR = "error"
    DONE = "done"
    UNAUTHORIZED = "unauthorized"
    FILE = "file"  # For file uploads (xlsx, csv, etc.)


@dataclass
class BotResponse:
    """Response chunk from bot processing."""

    type: BotResponseType
    content: Any
    agent_id: str | None = None
    formatted: FormattedMessage | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type.value,
            "content": self.content,
            "agent_id": self.agent_id,
            "formatted": self.formatted.content if self.formatted else None,
        }


class BotOrchestrator:
    """Central service for routing bot messages to agents.

    The orchestrator handles:
    - User authorization via linked platform accounts
    - Agent routing (default or @mentioned)
    - Message processing via PlaygroundRuntime
    - Response formatting for each platform
    - Comprehensive logging to database

    Example usage:
        orchestrator = BotOrchestrator(db, skills_registry)

        async for response in orchestrator.process_message(
            platform="telegram",
            platform_user_id="12345",
            platform_conversation_id="67890",
            message="@triage analyze ticket ESD-123",
        ):
            if response.type == BotResponseType.TEXT:
                send_to_platform(response.formatted)
    """

    # Agent mention pattern: @agent_name at start of message
    AGENT_MENTION_PATTERN = re.compile(r"^@(\w+)\s+(.+)", re.DOTALL)

    # Default agent for unrouted messages
    DEFAULT_AGENT = "triage"

    def __init__(
        self,
        db: Session,
        skills_registry: SkillsRegistry,
    ):
        """Initialize the bot orchestrator.

        Args:
            db: Database session
            skills_registry: Registry of available skills for agents
        """
        self.db = db
        self.skills = skills_registry
        self.formatters = FormatterRegistry()
        self.linking = UserLinkingService(db)
        self._runtime: PlaygroundRuntime | None = None

    @property
    def runtime(self) -> PlaygroundRuntime:
        """Get or create the PlaygroundRuntime instance."""
        if self._runtime is None:
            self._runtime = PlaygroundRuntime(
                skills_registry=self.skills,
                db_session=self.db,
            )
        return self._runtime

    async def process_message(
        self,
        platform: str,
        platform_user_id: str,
        platform_conversation_id: str,
        message: str,
        platform_message_id: str | None = None,
        platform_username: str | None = None,
    ) -> AsyncIterator[BotResponse]:
        """Process an incoming bot message.

        This is the main entry point for bot message processing. It:
        1. Verifies the user is authorized (linked account)
        2. Parses for agent mentions
        3. Routes to appropriate agent
        4. Yields response chunks for streaming
        5. Logs everything to database

        Args:
            platform: Platform name (telegram, slack, teams)
            platform_user_id: Platform-specific user ID
            platform_conversation_id: Chat/channel ID
            message: User message text
            platform_message_id: Optional platform message ID
            platform_username: Optional display name

        Yields:
            BotResponse chunks for real-time updates
        """
        start_time = time.perf_counter()
        formatter = self.formatters.get(platform)

        # Verify user authorization
        account = self.linking.get_linked_account(platform, platform_user_id)
        if not account:
            yield BotResponse(
                type=BotResponseType.UNAUTHORIZED,
                content="Your account is not linked to Atlas. Please link your account first.",
                formatted=formatter.format_error(
                    "Your account is not linked to Atlas. Use /link <code> to link your account."
                ),
            )
            return

        # Get or create conversation
        conversation = await self._get_or_create_conversation(
            platform=platform,
            platform_conversation_id=platform_conversation_id,
            account=account,
        )

        logger.info(
            f"Bot conversation: platform_conversation_id={platform_conversation_id}, "
            f"session_id={conversation.session_id}"
        )

        # Log inbound message
        await self._log_message(
            conversation=conversation,
            direction="inbound",
            content=message,
            platform_message_id=platform_message_id,
        )

        # Parse agent mention
        agent_id, cleaned_message = self._parse_agent_mention(message)

        # Update conversation with agent if specified
        if agent_id:
            conversation.agent_id = agent_id
            self.db.commit()

        # Yield typing indicator
        yield BotResponse(type=BotResponseType.TYPING, content=None)

        # Process with agent
        response_text = ""
        tool_calls: list[dict[str, Any]] = []
        input_tokens = 0
        output_tokens = 0
        error_msg: str | None = None

        try:
            # Get user info for tracking
            user = account.user
            user_id = None
            username = None

            if user:
                # SQLAlchemy eager-loaded relationship
                user_id = str(user.id) if user.id else None
                username = user.username
            elif hasattr(account, "user_id") and account.user_id:
                # MongoDB - look up user separately
                atlas_user = self.linking.get_user_by_platform(platform, platform_user_id)
                if atlas_user:
                    user_id = str(atlas_user.id) if hasattr(atlas_user, "id") else None
                    username = getattr(atlas_user, "username", None)

            print(f"[ORCHESTRATOR] Starting chat with agent={agent_id or self.DEFAULT_AGENT}", flush=True)
            async for event in self.runtime.chat(
                agent_id=agent_id or self.DEFAULT_AGENT,
                message=cleaned_message,
                session_id=conversation.session_id,
                user_id=user_id,
                username=username,
                client=platform,  # Track which platform the request came from
            ):
                print(f"[ORCHESTRATOR] Event type: {event.type}", flush=True)
                if event.type == ChatEventType.TOOL_START:
                    tool_name = event.data.get("tool", "unknown")
                    yield BotResponse(
                        type=BotResponseType.TOOL_CALL,
                        content={"tool": tool_name, "status": "started"},
                        agent_id=agent_id,
                    )

                elif event.type == ChatEventType.TOOL_END:
                    tool_name = event.data.get("tool", "unknown")
                    tool_calls.append({
                        "name": tool_name,
                        "duration_ms": event.data.get("duration_ms", 0),
                    })

                elif event.type == ChatEventType.MESSAGE_DELTA:
                    response_text = event.data.get("content", "")
                    logger.info(f"MESSAGE_DELTA received, content length: {len(response_text)}")

                elif event.type == ChatEventType.MESSAGE_END:
                    input_tokens = event.data.get("input_tokens", 0)
                    output_tokens = event.data.get("output_tokens", 0)

                elif event.type == ChatEventType.ERROR:
                    error_msg = event.data.get("error", "Unknown error")
                    yield BotResponse(
                        type=BotResponseType.ERROR,
                        content=error_msg,
                        formatted=formatter.format_error(error_msg),
                    )
                    break

                elif event.type == ChatEventType.FILE:
                    # File export event - yield directly for platform handlers
                    print(f"[ORCHESTRATOR] FILE event received: {event.data}", flush=True)
                    yield BotResponse(
                        type=BotResponseType.FILE,
                        content=event.data,
                        agent_id=agent_id,
                    )

            # Format final response
            logger.info(f"Bot processing complete, response_text length: {len(response_text)}, has_error: {bool(error_msg)}")
            if response_text:
                formatted = formatter.format_agent_response(
                    agent_id=agent_id or self.DEFAULT_AGENT,
                    response=response_text,
                    tool_calls=tool_calls if tool_calls else None,
                )

                yield BotResponse(
                    type=BotResponseType.TEXT,
                    content=response_text,
                    agent_id=agent_id,
                    formatted=formatted,
                )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Bot processing error: {error_msg}", exc_info=True)
            yield BotResponse(
                type=BotResponseType.ERROR,
                content=error_msg,
                formatted=formatter.format_error(f"An error occurred: {error_msg}"),
            )

        # Calculate metrics
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        cost_usd = 0.0  # Cost is tracked in playground runtime

        # Log outbound message
        if response_text or error_msg:
            await self._log_message(
                conversation=conversation,
                direction="outbound",
                content=response_text or f"Error: {error_msg}",
                agent_id=agent_id or self.DEFAULT_AGENT,
                tool_calls=tool_calls if tool_calls else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                duration_ms=duration_ms,
                error=error_msg,
            )

        # Update conversation timestamp
        conversation.last_message_at = datetime.now(UTC)
        self.db.commit()

        yield BotResponse(
            type=BotResponseType.DONE,
            content={
                "tokens": input_tokens + output_tokens,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
            },
        )

    def _parse_agent_mention(self, message: str) -> tuple[str | None, str]:
        """Parse @agent_name mention from message.

        Args:
            message: User message

        Returns:
            Tuple of (agent_id or None, cleaned message)
        """
        match = self.AGENT_MENTION_PATTERN.match(message.strip())
        if not match:
            return None, message

        agent_name = match.group(1).lower()
        cleaned_message = match.group(2).strip()

        # Validate agent exists
        if agent_name in AVAILABLE_AGENTS:
            return agent_name, cleaned_message

        # Check for aliases
        aliases = {
            "atlas": None,  # Route to default
            "help": None,
        }

        if agent_name in aliases:
            return aliases[agent_name], cleaned_message

        # Unknown agent - route to default but keep full message
        logger.warning(f"Unknown agent mentioned: {agent_name}")
        return None, message

    async def _get_or_create_conversation(
        self,
        platform: str,
        platform_conversation_id: str,
        account: BotPlatformAccount,
    ) -> BotConversation:
        """Get or create a conversation record.

        Args:
            platform: Platform name
            platform_conversation_id: Chat/channel ID
            account: Linked platform account

        Returns:
            BotConversation record
        """
        import os
        import uuid

        backend = os.getenv("ATLAS_STORAGE_BACKEND", "sqlite").lower()

        if backend == "mongodb":
            return await self._get_or_create_conversation_mongodb(
                platform, platform_conversation_id, account
            )

        # SQLAlchemy/SQLite path
        conversation = self.db.execute(
            select(BotConversation).where(
                BotConversation.platform == platform,
                BotConversation.platform_conversation_id == platform_conversation_id,
            )
        ).scalar_one_or_none()

        if conversation:
            return conversation

        # Create new conversation with session ID
        conversation = BotConversation(
            platform=platform,
            platform_conversation_id=platform_conversation_id,
            platform_account_id=account.id,
            session_id=str(uuid.uuid4()),
        )
        self.db.add(conversation)
        self.db.commit()

        logger.info(
            "Created bot conversation",
            extra={
                "platform": platform,
                "conversation_id": conversation.id,
                "session_id": conversation.session_id,
            },
        )

        return conversation

    async def _get_or_create_conversation_mongodb(
        self,
        platform: str,
        platform_conversation_id: str,
        account: BotPlatformAccount,
    ) -> BotConversation:
        """Get or create a conversation record in MongoDB."""
        import uuid
        from datetime import UTC, datetime

        from infrastructure_atlas.infrastructure.mongodb.client import get_mongodb_client

        db = get_mongodb_client().atlas
        collection = db["bot_conversations"]

        # Try to find existing conversation
        doc = collection.find_one({
            "platform": platform,
            "platform_conversation_id": platform_conversation_id,
        })

        if doc:
            # Return as a BotConversation-like object
            conv = BotConversation(
                platform=doc["platform"],
                platform_conversation_id=doc["platform_conversation_id"],
                platform_account_id=doc.get("platform_account_id"),
                session_id=doc["session_id"],
                agent_id=doc.get("agent_id"),
            )
            conv.id = doc["_id"]
            conv.last_message_at = doc.get("last_message_at")
            conv.created_at = doc.get("created_at")
            logger.debug(f"Found existing conversation: session_id={conv.session_id}")
            return conv

        # Create new conversation
        session_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        new_doc = {
            "_id": str(uuid.uuid4()),
            "platform": platform,
            "platform_conversation_id": platform_conversation_id,
            "platform_account_id": str(account.id) if account.id else None,
            "session_id": session_id,
            "agent_id": None,
            "last_message_at": now,
            "created_at": now,
        }
        collection.insert_one(new_doc)

        conv = BotConversation(
            platform=platform,
            platform_conversation_id=platform_conversation_id,
            platform_account_id=new_doc["platform_account_id"],
            session_id=session_id,
        )
        conv.id = new_doc["_id"]
        conv.last_message_at = now
        conv.created_at = now

        logger.info(
            f"Created bot conversation in MongoDB: session_id={session_id}, "
            f"platform_conversation_id={platform_conversation_id}"
        )

        return conv

    async def _log_message(
        self,
        conversation: BotConversation,
        direction: str,
        content: str,
        platform_message_id: str | None = None,
        agent_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> BotMessage | None:
        """Log a message to the database.

        Args:
            conversation: Conversation record
            direction: "inbound" or "outbound"
            content: Message content
            platform_message_id: Optional platform message ID
            agent_id: Agent that processed the message
            tool_calls: List of tool calls made
            input_tokens: Token count for input
            output_tokens: Token count for output
            cost_usd: Cost in USD
            duration_ms: Processing time
            error: Error message if any

        Returns:
            Created BotMessage record
        """
        import os

        backend = os.getenv("ATLAS_STORAGE_BACKEND", "sqlite").lower()

        if backend == "mongodb":
            return await self._log_message_mongodb(
                conversation, direction, content, platform_message_id,
                agent_id, tool_calls, input_tokens, output_tokens,
                cost_usd, duration_ms, error
            )

        # SQLAlchemy path
        try:
            message = BotMessage(
                conversation_id=conversation.id,
                direction=direction,
                content=content,
                platform_message_id=platform_message_id,
                agent_id=agent_id,
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                duration_ms=duration_ms,
                error=error,
            )
            self.db.add(message)
            self.db.commit()
            return message
        except Exception as e:
            logger.error(f"Failed to log bot message: {e!s}")
            self.db.rollback()
            return None

    async def _log_message_mongodb(
        self,
        conversation: BotConversation,
        direction: str,
        content: str,
        platform_message_id: str | None = None,
        agent_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> BotMessage | None:
        """Log a message to MongoDB."""
        import uuid
        from datetime import UTC, datetime

        from infrastructure_atlas.infrastructure.mongodb.client import get_mongodb_client

        try:
            db = get_mongodb_client().atlas
            collection = db["bot_messages"]

            doc = {
                "_id": str(uuid.uuid4()),
                "conversation_id": str(conversation.id),
                "direction": direction,
                "content": content,
                "platform_message_id": platform_message_id,
                "agent_id": agent_id,
                "tool_calls": tool_calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
                "error": error,
                "created_at": datetime.now(UTC),
            }
            collection.insert_one(doc)

            # Return a BotMessage-like object
            message = BotMessage(
                conversation_id=conversation.id,
                direction=direction,
                content=content,
                platform_message_id=platform_message_id,
                agent_id=agent_id,
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                duration_ms=duration_ms,
                error=error,
            )
            message.id = doc["_id"]
            return message

        except Exception as e:
            logger.error(f"Failed to log bot message to MongoDB: {e!s}")
            return None

    def get_available_agents(self) -> list[dict[str, Any]]:
        """Get list of available agents for help messages.

        Returns:
            List of agent info dictionaries
        """
        return [
            {
                "id": agent.id,
                "name": agent.name,
                "description": agent.description,
            }
            for agent in AVAILABLE_AGENTS.values()
        ]

    def get_conversation_history(
        self,
        conversation_id: int,
        limit: int = 50,
    ) -> list[BotMessage]:
        """Get recent messages for a conversation.

        Args:
            conversation_id: Conversation ID
            limit: Maximum messages to return

        Returns:
            List of BotMessage records
        """
        return list(
            self.db.execute(
                select(BotMessage)
                .where(BotMessage.conversation_id == conversation_id)
                .order_by(BotMessage.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def get_user_conversations(
        self,
        user_id: str,
        platform: str | None = None,
        limit: int = 20,
    ) -> list[BotConversation]:
        """Get conversations for a user.

        Args:
            user_id: Atlas user ID
            platform: Optional platform filter
            limit: Maximum conversations to return

        Returns:
            List of BotConversation records
        """
        # Get user's platform accounts
        accounts = self.linking.get_user_accounts(user_id, platform)
        if not accounts:
            return []

        account_ids = [a.id for a in accounts]

        query = (
            select(BotConversation)
            .where(BotConversation.platform_account_id.in_(account_ids))
            .order_by(BotConversation.last_message_at.desc())
            .limit(limit)
        )

        return list(self.db.execute(query).scalars().all())
