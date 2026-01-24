"""Factory for creating bot services with the correct storage backend.

This module provides a unified way to create bot services that work with
either SQLAlchemy (SQLite) or MongoDB backends, based on the configured
ATLAS_STORAGE_BACKEND environment variable.
"""

from __future__ import annotations

import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Iterator

from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.infrastructure.repository_factory import get_storage_backend

if TYPE_CHECKING:
    from infrastructure_atlas.bots.linking import UserLinkingService
    from infrastructure_atlas.bots.orchestrator import BotOrchestrator
    from infrastructure_atlas.skills import SkillsRegistry

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# MongoDB Session Wrapper
# ---------------------------------------------------------------------------


class MongoDBBotSession:
    """MongoDB-backed session that provides bot repository access.

    This class mimics enough of the SQLAlchemy session interface to work
    with the existing bot code while using MongoDB repositories underneath.
    """

    def __init__(self) -> None:
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client
        from infrastructure_atlas.infrastructure.mongodb.repositories import (
            MongoDBBotConversationRepository,
            MongoDBBotMessageRepository,
            MongoDBBotPlatformAccountRepository,
            MongoDBUserRepository,
        )

        client = get_mongodb_client()
        self._db = client.atlas
        self._platform_accounts = MongoDBBotPlatformAccountRepository(self._db)
        self._conversations = MongoDBBotConversationRepository(self._db)
        self._messages = MongoDBBotMessageRepository(self._db)
        self._users = MongoDBUserRepository(self._db)

    @property
    def platform_accounts(self) -> Any:
        return self._platform_accounts

    @property
    def conversations(self) -> Any:
        return self._conversations

    @property
    def messages(self) -> Any:
        return self._messages

    @property
    def users(self) -> Any:
        return self._users


@contextmanager
def get_bot_session() -> Iterator[Any]:
    """Get a database session for bot operations.

    Returns either a SQLAlchemy session or MongoDB session wrapper
    based on the ATLAS_STORAGE_BACKEND environment variable.
    """
    backend = get_storage_backend()

    if backend == "mongodb":
        # Use MongoDB session wrapper
        session = MongoDBBotSession()
        yield session
    else:
        # Use SQLite via SQLAlchemy
        from infrastructure_atlas.db import get_sessionmaker
        SessionLocal = get_sessionmaker()
        with SessionLocal() as session:
            yield session


def create_bot_orchestrator(session: Any, skills: "SkillsRegistry") -> "BotOrchestrator":
    """Create a BotOrchestrator.

    Returns either the SQLAlchemy-based or MongoDB-based orchestrator
    depending on the session type.
    """
    if isinstance(session, MongoDBBotSession):
        return MongoDBBotOrchestrator(session, skills)
    else:
        from infrastructure_atlas.bots.orchestrator import BotOrchestrator
        return BotOrchestrator(session, skills)


def create_user_linking_service(session: Any) -> "UserLinkingService":
    """Create a UserLinkingService.

    Returns either the SQLAlchemy-based or MongoDB-based service
    depending on the session type.
    """
    if isinstance(session, MongoDBBotSession):
        return MongoDBUserLinkingService(session)
    else:
        from infrastructure_atlas.bots.linking import UserLinkingService
        return UserLinkingService(session)


# ---------------------------------------------------------------------------
# MongoDB-specific implementations
# ---------------------------------------------------------------------------


class MongoDBUserLinkingService:
    """MongoDB-backed UserLinkingService implementation.

    Manages linking external platform accounts to Atlas users.
    """

    # Verification code settings (match SQLAlchemy implementation)
    CODE_LENGTH = 6
    CODE_EXPIRY_MINUTES = 10

    def __init__(self, session: MongoDBBotSession) -> None:
        self._session = session
        self._accounts = session.platform_accounts
        self._users = session.users

    def generate_verification_code(
        self,
        user_id: str,
        platform: str,
        platform_user_id: str | None = None,
        platform_username: str | None = None,
    ) -> str:
        """Generate a verification code for linking a platform account.

        Args:
            user_id: Atlas user ID
            platform: Platform name (telegram, slack, teams)
            platform_user_id: Optional platform user ID (if known ahead of time)
            platform_username: Optional display name from platform

        Returns:
            6-digit verification code
        """
        from infrastructure_atlas.domain.entities import BotPlatformAccountEntity

        # Check for existing unverified account
        existing = self._accounts.get_unverified_by_user_and_platform(user_id, platform)

        # Generate new code
        code = "".join(secrets.choice("0123456789") for _ in range(self.CODE_LENGTH))
        expires = datetime.now(UTC) + timedelta(minutes=self.CODE_EXPIRY_MINUTES)

        if existing:
            # Update existing unverified account
            updates = {
                "verification_code": code,
                "verification_expires": expires,
            }
            if platform_user_id:
                updates["platform_user_id"] = platform_user_id
            if platform_username:
                updates["platform_username"] = platform_username

            # Update via repository's update method
            self._accounts._collection.update_one(
                {"_id": existing.id},
                {"$set": {**updates, "updated_at": datetime.now(UTC)}},
            )
        else:
            # Create new unverified account
            next_id = self._accounts.get_next_id()
            now = datetime.now(UTC)
            account = BotPlatformAccountEntity(
                id=next_id,
                user_id=user_id,
                platform=platform,
                platform_user_id=platform_user_id or f"pending:{user_id}",
                platform_username=platform_username,
                verified=False,
                verification_code=code,
                verification_expires=expires,
                created_at=now,
                updated_at=now,
            )
            self._accounts.create(account)

        return code

    def verify_code(
        self,
        platform: str,
        platform_user_id: str,
        code: str,
        platform_username: str | None = None,
    ) -> Any | None:
        """Verify a code and link the platform account.

        Args:
            platform: Platform name (telegram, slack, teams)
            platform_user_id: Platform-specific user ID
            code: Verification code from user
            platform_username: Optional display name to update

        Returns:
            The linked BotPlatformAccount if successful, None otherwise
        """
        now = datetime.now(UTC)

        # Find account with matching code (not expired)
        account = self._accounts.get_unverified_by_platform_and_code(platform, code)
        if not account:
            return None

        # Check expiry
        if account.verification_expires:
            expires = account.verification_expires
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires < now:
                return None

        # Check if this platform user is already linked to a verified account
        existing = self._accounts.get_verified_by_platform_user(platform, platform_user_id)

        if existing:
            if existing.user_id == account.user_id:
                # Already linked to the same user - delete the pending request
                self._accounts.delete(account.id)
                return existing
            else:
                # Linked to a different user - unlink the old one first
                self._accounts.delete(existing.id)

        # Update account with verified info
        self._accounts._collection.update_one(
            {"_id": account.id},
            {"$set": {
                "platform_user_id": platform_user_id,
                "platform_username": platform_username if platform_username else account.platform_username,
                "verified": True,
                "verification_code": None,
                "verification_expires": None,
                "updated_at": now,
            }},
        )

        # Return updated account
        return self._accounts.get_by_id(account.id)

    def get_linked_account(self, platform: str, platform_user_id: str) -> Any | None:
        """Get a linked account if it exists and is verified.

        Args:
            platform: Platform name
            platform_user_id: Platform-specific user ID

        Returns:
            BotPlatformAccountEntity if found and verified, None otherwise
        """
        return self._accounts.get_verified_by_platform_user(platform, platform_user_id)

    def get_user_accounts(self, user_id: str, platform: str | None = None) -> list[Any]:
        """Get all linked accounts for a user.

        Args:
            user_id: Atlas user ID
            platform: Optional platform filter

        Returns:
            List of BotPlatformAccountEntity objects
        """
        return self._accounts.get_by_user_id(user_id, platform)

    def unlink_account(self, account_id: int) -> bool:
        """Unlink a platform account.

        Args:
            account_id: BotPlatformAccount ID

        Returns:
            True if account was deleted, False if not found
        """
        return self._accounts.delete(account_id)

    def unlink_user_platform(self, user_id: str, platform: str) -> bool:
        """Unlink all accounts for a user on a specific platform.

        Args:
            user_id: Atlas user ID
            platform: Platform name

        Returns:
            True if any accounts were deleted
        """
        count = self._accounts.delete_by_user_id(user_id, platform)
        return count > 0

    def get_user_by_platform(self, platform: str, platform_user_id: str) -> Any | None:
        """Get Atlas user from their platform account.

        Args:
            platform: Platform name
            platform_user_id: Platform-specific user ID

        Returns:
            UserEntity if found and account is verified, None otherwise
        """
        account = self.get_linked_account(platform, platform_user_id)
        if not account:
            return None

        return self._users.get_by_id(account.user_id)

    def cleanup_expired_codes(self) -> int:
        """Remove expired verification codes.

        Returns:
            Number of accounts with expired codes that were cleaned up
        """
        now = datetime.now(UTC)
        count = 0

        # Find all unverified accounts with expired codes
        cursor = self._accounts._collection.find({
            "verified": False,
            "verification_expires": {"$lt": now},
        })

        for doc in cursor:
            # Delete accounts that were never verified (pending placeholder)
            if doc.get("platform_user_id", "").startswith("pending:"):
                self._accounts.delete(doc["_id"])
            else:
                # Clear code but keep account for potential re-verification
                self._accounts._collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"verification_code": None, "verification_expires": None}},
                )
            count += 1

        return count


class MongoDBBotOrchestrator:
    """MongoDB-backed BotOrchestrator implementation.

    Central service for routing bot messages to agents.
    """

    # Agent mention pattern: @agent_name at start of message
    AGENT_MENTION_PATTERN = re.compile(r"^@(\w+)\s+(.+)", re.DOTALL)

    # Default agent for unrouted messages
    DEFAULT_AGENT = "ops"

    def __init__(self, session: MongoDBBotSession, skills: "SkillsRegistry") -> None:
        self._session = session
        self._skills = skills
        self._accounts = session.platform_accounts
        self._conversations = session.conversations
        self._messages = session.messages
        self._users = session.users
        self._linking = MongoDBUserLinkingService(session)
        self._runtime = None

    @property
    def runtime(self) -> Any:
        """Get or create the PlaygroundRuntime instance."""
        if self._runtime is None:
            from infrastructure_atlas.agents.playground import PlaygroundRuntime
            self._runtime = PlaygroundRuntime(
                skills_registry=self._skills,
                db_session=None,  # MongoDB doesn't need SQLAlchemy session
            )
        return self._runtime

    @property
    def linking(self) -> MongoDBUserLinkingService:
        """Get the linking service."""
        return self._linking

    @property
    def formatters(self) -> Any:
        """Get formatter registry."""
        from infrastructure_atlas.bots.formatters import FormatterRegistry
        return FormatterRegistry()

    async def process_message(
        self,
        platform: str,
        platform_user_id: str,
        platform_conversation_id: str,
        message: str,
        platform_message_id: str | None = None,
        platform_username: str | None = None,
        platform_user_info: dict[str, Any] | None = None,
    ) -> AsyncIterator[Any]:
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
            platform_user_info: Optional dict with platform user details (email, display_name, etc.)

        Yields:
            BotResponse chunks for real-time updates
        """
        from infrastructure_atlas.agents.playground import ChatEventType
        from infrastructure_atlas.bots.orchestrator import BotResponse, BotResponseType

        start_time = time.perf_counter()
        formatter = self.formatters.get(platform)

        # Verify user authorization
        account = self._linking.get_linked_account(platform, platform_user_id)
        if not account:
            yield BotResponse(
                type=BotResponseType.UNAUTHORIZED,
                content="Your account is not linked to Atlas. Please link your account first.",
                formatted=formatter.format_error(
                    "Your account is not linked to Atlas. Use /link <code> to link your account."
                ),
            )
            return

        # Get user
        user = self._users.get_by_id(account.user_id) if account.user_id else None

        # Get or create conversation
        conversation = await self._get_or_create_conversation(
            platform=platform,
            platform_conversation_id=platform_conversation_id,
            account=account,
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
            self._conversations._collection.update_one(
                {"_id": conversation.id},
                {"$set": {"agent_id": agent_id}},
            )

        # Yield typing indicator
        yield BotResponse(type=BotResponseType.TYPING, content=None)

        # Process with agent
        response_text = ""
        tool_calls: list[dict[str, Any]] = []
        input_tokens = 0
        output_tokens = 0
        error_msg: str | None = None

        try:
            async for event in self.runtime.chat(
                agent_id=agent_id or self.DEFAULT_AGENT,
                message=cleaned_message,
                session_id=conversation.session_id,
                user_id=user.id if user else None,
                username=user.username if user else None,
                client=platform,
                platform_user_info=platform_user_info,
            ):
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
                    yield BotResponse(
                        type=BotResponseType.FILE,
                        content=event.data,
                        agent_id=agent_id,
                    )

            # Format final response
            logger.debug(f"[ORCHESTRATOR] After event loop: response_text length={len(response_text)}, has_error={bool(error_msg)}")
            if response_text:
                formatted = formatter.format_agent_response(
                    agent_id=agent_id or self.DEFAULT_AGENT,
                    response=response_text,
                    tool_calls=tool_calls if tool_calls else None,
                )

                logger.debug(f"[ORCHESTRATOR] Yielding TEXT response with {len(response_text)} chars")
                yield BotResponse(
                    type=BotResponseType.TEXT,
                    content=response_text,
                    agent_id=agent_id,
                    formatted=formatted,
                )
            else:
                logger.warning(f"[ORCHESTRATOR] No response_text to yield! error_msg={error_msg}")

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
        cost_usd = 0.0

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
        self._conversations.update_last_message_at(conversation.id, datetime.now(UTC))

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
        from infrastructure_atlas.agents.playground import AVAILABLE_AGENTS

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
        account: Any,
    ) -> Any:
        """Get or create a conversation record.

        Args:
            platform: Platform name
            platform_conversation_id: Chat/channel ID
            account: Linked platform account

        Returns:
            BotConversationEntity record
        """
        from infrastructure_atlas.domain.entities import BotConversationEntity

        # Try to find existing conversation
        conversation = self._conversations.get_by_platform_conversation(
            platform, platform_conversation_id
        )

        if conversation:
            return conversation

        # Create new conversation with session ID
        now = datetime.now(UTC)
        next_id = self._conversations.get_next_id()
        conversation = BotConversationEntity(
            id=next_id,
            platform=platform,
            platform_conversation_id=platform_conversation_id,
            platform_account_id=account.id,
            agent_id=None,
            session_id=str(uuid.uuid4()),
            created_at=now,
            last_message_at=now,
        )
        self._conversations.create(conversation)

        logger.info(
            "Created bot conversation",
            extra={
                "platform": platform,
                "conversation_id": conversation.id,
                "session_id": conversation.session_id,
            },
        )

        return conversation

    async def _log_message(
        self,
        conversation: Any,
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
    ) -> Any:
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
            Created BotMessageEntity record
        """
        from infrastructure_atlas.domain.entities import BotMessageEntity

        try:
            now = datetime.now(UTC)
            next_id = self._messages.get_next_id()
            message = BotMessageEntity(
                id=next_id,
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
                created_at=now,
            )
            self._messages.create(message)
            return message
        except Exception as e:
            logger.error(f"Failed to log bot message: {e!s}")
            return None

    def get_available_agents(self) -> list[dict[str, Any]]:
        """Get list of available agents for help messages.

        Returns:
            List of agent info dictionaries
        """
        from infrastructure_atlas.agents.playground import AVAILABLE_AGENTS

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
    ) -> list[Any]:
        """Get recent messages for a conversation.

        Args:
            conversation_id: Conversation ID
            limit: Maximum messages to return

        Returns:
            List of BotMessageEntity records
        """
        return self._messages.get_by_conversation_id(conversation_id, limit)

    def get_user_conversations(
        self,
        user_id: str,
        platform: str | None = None,
        limit: int = 20,
    ) -> list[Any]:
        """Get conversations for a user.

        Args:
            user_id: Atlas user ID
            platform: Optional platform filter
            limit: Maximum conversations to return

        Returns:
            List of BotConversationEntity records
        """
        # Get user's platform accounts
        accounts = self._linking.get_user_accounts(user_id, platform)
        if not accounts:
            return []

        # Get conversations for all accounts
        conversations = []
        for account in accounts:
            convs = self._conversations.get_by_account_id(account.id, limit=limit)
            conversations.extend(convs)

        # Sort by last_message_at descending and limit
        conversations.sort(key=lambda c: c.last_message_at, reverse=True)
        return conversations[:limit]
