"""MongoDB-backed repository implementations.

Implements the domain repository protocols using MongoDB as the storage backend.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from infrastructure_atlas.domain.entities import (
    BotConversationEntity,
    BotMessageEntity,
    BotPlatformAccountEntity,
    BotWebhookConfigEntity,
    ChatMessageEntity,
    ChatSessionEntity,
    ForemanConfigEntity,
    GlobalAPIKeyEntity,
    PuppetConfigEntity,
    RolePermissionEntity,
    UserAPIKeyEntity,
    UserEntity,
    VCenterConfigEntity,
)
from infrastructure_atlas.domain.repositories import (
    ChatSessionRepository,
    ForemanConfigRepository,
    GlobalAPIKeyRepository,
    RolePermissionRepository,
    UserAPIKeyRepository,
    UserRepository,
    VCenterConfigRepository,
)

from . import mappers


def _now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(UTC)


class MongoDBUserRepository(UserRepository):
    """MongoDB implementation of UserRepository."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["users"]

    def get_by_id(self, user_id: str) -> UserEntity | None:
        doc = self._collection.find_one({"_id": user_id})
        return mappers.document_to_user(doc) if doc else None

    def get_by_username(self, username: str) -> UserEntity | None:
        doc = self._collection.find_one({"username": username})
        return mappers.document_to_user(doc) if doc else None

    def list_all(self) -> list[UserEntity]:
        cursor = self._collection.find().sort("created_at", 1)
        return [mappers.document_to_user(doc) for doc in cursor]

    def create(
        self,
        *,
        user_id: str | None = None,
        username: str,
        display_name: str | None = None,
        email: str | None = None,
        role: str = "member",
        password_hash: str | None = None,
        is_active: bool = True,
    ) -> UserEntity:
        """Create a new user."""
        now = _now_utc()
        doc = {
            "_id": user_id or str(uuid.uuid4()),
            "username": username,
            "display_name": display_name,
            "email": email,
            "role": role,
            "password_hash": password_hash,
            "is_active": is_active,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self._collection.insert_one(doc)
        except DuplicateKeyError as exc:
            raise ValueError("A user with that username already exists") from exc
        return mappers.document_to_user(doc)

    def update(
        self,
        user_id: str,
        *,
        username: str | None = None,
        display_name: str | None = ...,  # type: ignore[assignment]
        email: str | None = ...,  # type: ignore[assignment]
        role: str | None = None,
        password_hash: str | None = ...,  # type: ignore[assignment]
        is_active: bool | None = None,
    ) -> UserEntity | None:
        """Update an existing user."""
        updates: dict[str, Any] = {"updated_at": _now_utc()}
        if username is not None:
            updates["username"] = username
        if display_name is not ...:
            updates["display_name"] = display_name
        if email is not ...:
            updates["email"] = email
        if role is not None:
            updates["role"] = role
        if password_hash is not ...:
            updates["password_hash"] = password_hash
        if is_active is not None:
            updates["is_active"] = is_active

        try:
            result = self._collection.find_one_and_update(
                {"_id": user_id},
                {"$set": updates},
                return_document=True,
            )
        except DuplicateKeyError as exc:
            raise ValueError("A user with that username already exists") from exc

        return mappers.document_to_user(result) if result else None

    def delete(self, user_id: str) -> bool:
        """Delete a user."""
        result = self._collection.delete_one({"_id": user_id})
        return result.deleted_count > 0


class MongoDBUserAPIKeyRepository(UserAPIKeyRepository):
    """MongoDB implementation of UserAPIKeyRepository."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["user_api_keys"]

    def list_for_user(self, user_id: str) -> list[UserAPIKeyEntity]:
        cursor = self._collection.find({"user_id": user_id})
        return [mappers.document_to_user_api_key(doc) for doc in cursor]

    def get(self, user_id: str, provider: str) -> UserAPIKeyEntity | None:
        doc = self._collection.find_one({"user_id": user_id, "provider": provider})
        return mappers.document_to_user_api_key(doc) if doc else None

    def upsert(
        self,
        *,
        user_id: str,
        provider: str,
        label: str | None = None,
        secret: str,
    ) -> UserAPIKeyEntity:
        """Create or update a user API key."""
        now = _now_utc()
        doc = {
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "provider": provider,
            "label": label,
            "secret": secret,
            "created_at": now,
            "updated_at": now,
        }
        result = self._collection.find_one_and_update(
            {"user_id": user_id, "provider": provider},
            {
                "$set": {"label": label, "secret": secret, "updated_at": now},
                "$setOnInsert": {"_id": doc["_id"], "created_at": now},
            },
            upsert=True,
            return_document=True,
        )
        return mappers.document_to_user_api_key(result)

    def delete(self, user_id: str, provider: str) -> bool:
        """Delete a user API key."""
        result = self._collection.delete_one({"user_id": user_id, "provider": provider})
        return result.deleted_count > 0


class MongoDBGlobalAPIKeyRepository(GlobalAPIKeyRepository):
    """MongoDB implementation of GlobalAPIKeyRepository."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["global_api_keys"]

    def list_all(self) -> list[GlobalAPIKeyEntity]:
        cursor = self._collection.find().sort("provider", 1)
        return [mappers.document_to_global_api_key(doc) for doc in cursor]

    def get(self, provider: str) -> GlobalAPIKeyEntity | None:
        doc = self._collection.find_one({"provider": provider})
        return mappers.document_to_global_api_key(doc) if doc else None

    def upsert(
        self,
        *,
        provider: str,
        label: str | None = None,
        secret: str,
    ) -> GlobalAPIKeyEntity:
        """Create or update a global API key."""
        now = _now_utc()
        result = self._collection.find_one_and_update(
            {"provider": provider},
            {
                "$set": {"label": label, "secret": secret, "updated_at": now},
                "$setOnInsert": {"_id": str(uuid.uuid4()), "created_at": now},
            },
            upsert=True,
            return_document=True,
        )
        return mappers.document_to_global_api_key(result)

    def delete(self, provider: str) -> bool:
        """Delete a global API key."""
        result = self._collection.delete_one({"provider": provider})
        return result.deleted_count > 0


class MongoDBChatSessionRepository(ChatSessionRepository):
    """MongoDB implementation of ChatSessionRepository."""

    def __init__(self, db: Database) -> None:
        self._sessions: Collection = db["chat_sessions"]
        self._messages: Collection = db["chat_messages"]

    def list_sessions(
        self,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[ChatSessionEntity]:
        query: dict[str, Any] = {}
        if user_id:
            query["user_id"] = user_id
        cursor = self._sessions.find(query).sort("updated_at", -1).limit(limit)
        return [mappers.document_to_chat_session(doc) for doc in cursor]

    def get_session(self, session_id: str) -> ChatSessionEntity | None:
        doc = self._sessions.find_one({"session_id": session_id})
        return mappers.document_to_chat_session(doc) if doc else None

    def get_session_by_internal_id(self, internal_id: str) -> ChatSessionEntity | None:
        """Get a session by its internal MongoDB _id."""
        doc = self._sessions.find_one({"_id": internal_id})
        return mappers.document_to_chat_session(doc) if doc else None

    def get_messages(self, session_id: str) -> list[ChatMessageEntity]:
        """Get messages by session_id (the external string ID)."""
        # First get the internal session ID
        session = self._sessions.find_one({"session_id": session_id})
        if not session:
            return []
        internal_id = str(session["_id"])
        cursor = self._messages.find({"session_id": internal_id}).sort("created_at", 1)
        return [mappers.document_to_chat_message(doc) for doc in cursor]

    def get_messages_by_internal_id(self, internal_session_id: str) -> list[ChatMessageEntity]:
        """Get messages by internal session _id."""
        cursor = self._messages.find({"session_id": internal_session_id}).sort("created_at", 1)
        return [mappers.document_to_chat_message(doc) for doc in cursor]

    def iter_messages(self, session_id: str) -> Iterator[ChatMessageEntity]:
        # First get the internal session ID
        session = self._sessions.find_one({"session_id": session_id})
        if not session:
            return
        internal_id = str(session["_id"])
        cursor = self._messages.find({"session_id": internal_id}).sort("created_at", 1)
        for doc in cursor:
            yield mappers.document_to_chat_message(doc)

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        title: str = "New AI Chat",
        provider_type: str | None = None,
        model: str | None = None,
        context_variables: dict | None = None,
    ) -> ChatSessionEntity:
        """Create a new chat session."""
        now = _now_utc()
        doc = {
            "_id": str(uuid.uuid4()),
            "session_id": session_id,
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "provider_type": provider_type,
            "model": model,
            "context_variables": context_variables or {},
        }
        try:
            self._sessions.insert_one(doc)
        except DuplicateKeyError as exc:
            raise ValueError("A session with that ID already exists") from exc
        return mappers.document_to_chat_session(doc)

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        message_type: str | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        metadata_json: dict | None = None,
    ) -> ChatMessageEntity:
        """Add a message to a session.

        Note: session_id here is the internal MongoDB _id of the session.
        """
        now = _now_utc()
        doc = {
            "_id": str(uuid.uuid4()),
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": now,
            "message_type": message_type,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "metadata_json": metadata_json,
        }
        self._messages.insert_one(doc)
        # Update session's updated_at
        self._sessions.update_one({"_id": session_id}, {"$set": {"updated_at": now}})
        return mappers.document_to_chat_message(doc)

    def update_session_title(self, session_id: str, title: str) -> ChatSessionEntity | None:
        """Update a session's title."""
        result = self._sessions.find_one_and_update(
            {"session_id": session_id},
            {"$set": {"title": title, "updated_at": _now_utc()}},
            return_document=True,
        )
        return mappers.document_to_chat_session(result) if result else None

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        provider_type: str | None = None,
        model: str | None = None,
    ) -> ChatSessionEntity | None:
        """Update multiple session fields."""
        updates: dict[str, Any] = {"updated_at": _now_utc()}
        if title is not None:
            updates["title"] = title
        if provider_type is not None:
            updates["provider_type"] = provider_type
        # Allow model to be explicitly set to None
        updates["model"] = model

        result = self._sessions.find_one_and_update(
            {"session_id": session_id},
            {"$set": updates},
            return_document=True,
        )
        return mappers.document_to_chat_session(result) if result else None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its messages."""
        # First get the internal _id
        session = self._sessions.find_one({"session_id": session_id})
        if not session:
            return False
        internal_id = str(session["_id"])
        # Delete messages first (by internal session ID)
        self._messages.delete_many({"session_id": internal_id})
        # Delete session
        result = self._sessions.delete_one({"session_id": session_id})
        return result.deleted_count > 0

    def count_messages(self, session_id: str) -> int:
        """Count messages in a session by external session_id."""
        session = self._sessions.find_one({"session_id": session_id})
        if not session:
            return 0
        internal_id = str(session["_id"])
        return self._messages.count_documents({"session_id": internal_id})


class MongoDBRolePermissionRepository(RolePermissionRepository):
    """MongoDB implementation of RolePermissionRepository."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["role_permissions"]

    def list_all(self) -> list[RolePermissionEntity]:
        cursor = self._collection.find().sort("role", 1)
        return [mappers.document_to_role_permission(doc) for doc in cursor]

    def get(self, role: str) -> RolePermissionEntity | None:
        doc = self._collection.find_one({"_id": role})
        return mappers.document_to_role_permission(doc) if doc else None

    def upsert(
        self,
        role: str,
        label: str,
        description: str | None,
        permissions: Iterable[str],
    ) -> RolePermissionEntity:
        """Create or update a role's permissions."""
        label_clean = (label or role).strip() or role
        description_clean = description.strip() if isinstance(description, str) and description.strip() else None
        cleaned_perms = sorted({str(perm).strip() for perm in permissions if perm and str(perm).strip()})
        now = _now_utc()

        result = self._collection.find_one_and_update(
            {"_id": role},
            {
                "$set": {
                    "role": role,
                    "label": label_clean,
                    "description": description_clean,
                    "permissions": cleaned_perms,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
            return_document=True,
        )
        return mappers.document_to_role_permission(result)

    def delete(self, role: str) -> bool:
        """Delete a role permission record."""
        result = self._collection.delete_one({"_id": role})
        return result.deleted_count > 0


class MongoDBVCenterConfigRepository(VCenterConfigRepository):
    """MongoDB implementation of VCenterConfigRepository."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["vcenter_configs"]

    def list_all(self) -> list[VCenterConfigEntity]:
        cursor = self._collection.find().sort("name", 1)
        return [mappers.document_to_vcenter_config(doc) for doc in cursor]

    def get(self, config_id: str) -> VCenterConfigEntity | None:
        doc = self._collection.find_one({"_id": config_id})
        return mappers.document_to_vcenter_config(doc) if doc else None

    def create(  # noqa: PLR0913
        self,
        *,
        config_id: str | None,
        name: str,
        base_url: str,
        username: str,
        password_secret: str,
        verify_ssl: bool,
        is_esxi: bool = False,
    ) -> VCenterConfigEntity:
        """Create a new vCenter configuration."""
        now = _now_utc()
        doc = {
            "_id": config_id or str(uuid.uuid4()),
            "name": name,
            "base_url": base_url,
            "username": username,
            "password_secret": password_secret,
            "verify_ssl": verify_ssl,
            "is_esxi": is_esxi,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self._collection.insert_one(doc)
        except DuplicateKeyError as exc:
            raise ValueError("A vCenter with that name already exists") from exc
        return mappers.document_to_vcenter_config(doc)

    def update(  # noqa: PLR0913
        self,
        config_id: str,
        *,
        name: str | None = None,
        base_url: str | None = None,
        username: str | None = None,
        verify_ssl: bool | None = None,
        password_secret: str | None = None,
        is_esxi: bool | None = None,
    ) -> VCenterConfigEntity | None:
        """Update an existing vCenter configuration."""
        updates: dict[str, Any] = {"updated_at": _now_utc()}
        if name is not None:
            updates["name"] = name
        if base_url is not None:
            updates["base_url"] = base_url
        if username is not None:
            updates["username"] = username
        if verify_ssl is not None:
            updates["verify_ssl"] = verify_ssl
        if password_secret is not None:
            updates["password_secret"] = password_secret
        if is_esxi is not None:
            updates["is_esxi"] = is_esxi

        try:
            result = self._collection.find_one_and_update(
                {"_id": config_id},
                {"$set": updates},
                return_document=True,
            )
        except DuplicateKeyError as exc:
            raise ValueError("A vCenter with that name already exists") from exc

        return mappers.document_to_vcenter_config(result) if result else None

    def delete(self, config_id: str) -> bool:
        """Delete a vCenter configuration."""
        result = self._collection.delete_one({"_id": config_id})
        return result.deleted_count > 0


class MongoDBForemanConfigRepository(ForemanConfigRepository):
    """MongoDB implementation of ForemanConfigRepository."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["foreman_configs"]

    def list_all(self) -> list[ForemanConfigEntity]:
        cursor = self._collection.find().sort("name", 1)
        return [mappers.document_to_foreman_config(doc) for doc in cursor]

    def get(self, config_id: str) -> ForemanConfigEntity | None:
        doc = self._collection.find_one({"_id": config_id})
        return mappers.document_to_foreman_config(doc) if doc else None

    def create(  # noqa: PLR0913
        self,
        *,
        config_id: str | None,
        name: str,
        base_url: str,
        username: str,
        token_secret: str,
        verify_ssl: bool,
    ) -> ForemanConfigEntity:
        """Create a new Foreman configuration."""
        now = _now_utc()
        doc = {
            "_id": config_id or str(uuid.uuid4()),
            "name": name,
            "base_url": base_url,
            "username": username,
            "token_secret": token_secret,
            "verify_ssl": verify_ssl,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self._collection.insert_one(doc)
        except DuplicateKeyError as exc:
            raise ValueError("A Foreman with that name already exists") from exc
        return mappers.document_to_foreman_config(doc)

    def update(  # noqa: PLR0913
        self,
        config_id: str,
        *,
        name: str | None = None,
        base_url: str | None = None,
        username: str | None = None,
        verify_ssl: bool | None = None,
        token_secret: str | None = None,
    ) -> ForemanConfigEntity | None:
        """Update an existing Foreman configuration."""
        updates: dict[str, Any] = {"updated_at": _now_utc()}
        if name is not None:
            updates["name"] = name
        if base_url is not None:
            updates["base_url"] = base_url
        if username is not None:
            updates["username"] = username
        if verify_ssl is not None:
            updates["verify_ssl"] = verify_ssl
        if token_secret is not None:
            updates["token_secret"] = token_secret

        try:
            result = self._collection.find_one_and_update(
                {"_id": config_id},
                {"$set": updates},
                return_document=True,
            )
        except DuplicateKeyError as exc:
            raise ValueError("A Foreman with that name already exists") from exc

        return mappers.document_to_foreman_config(result) if result else None

    def delete(self, config_id: str) -> bool:
        """Delete a Foreman configuration."""
        result = self._collection.delete_one({"_id": config_id})
        return result.deleted_count > 0


# ---------------------------------------------------------------------------
# Puppet Config Repository
# ---------------------------------------------------------------------------


class MongoDBPuppetConfigRepository:
    """MongoDB implementation of Puppet config repository."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["puppet_configs"]

    def list_all(self) -> list[PuppetConfigEntity]:
        cursor = self._collection.find().sort("name", 1)
        return [mappers.document_to_puppet_config(doc) for doc in cursor]

    def get(self, config_id: str) -> PuppetConfigEntity | None:
        doc = self._collection.find_one({"_id": config_id})
        return mappers.document_to_puppet_config(doc) if doc else None

    def create(
        self,
        *,
        config_id: str | None,
        name: str,
        remote_url: str,
        branch: str,
        ssh_key_secret: str | None,
        local_path: str | None,
    ) -> PuppetConfigEntity:
        """Create a new Puppet configuration."""
        now = _now_utc()
        doc = {
            "_id": config_id or str(uuid.uuid4()),
            "name": name,
            "remote_url": remote_url,
            "branch": branch,
            "ssh_key_secret": ssh_key_secret,
            "local_path": local_path,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self._collection.insert_one(doc)
        except DuplicateKeyError as exc:
            raise ValueError("A Puppet configuration with that name already exists") from exc
        return mappers.document_to_puppet_config(doc)

    def update(
        self,
        config_id: str,
        *,
        name: str | None = None,
        remote_url: str | None = None,
        branch: str | None = None,
        ssh_key_secret: str | None = None,
        local_path: str | None = None,
    ) -> PuppetConfigEntity | None:
        """Update an existing Puppet configuration."""
        updates: dict[str, Any] = {"updated_at": _now_utc()}
        if name is not None:
            updates["name"] = name
        if remote_url is not None:
            updates["remote_url"] = remote_url
        if branch is not None:
            updates["branch"] = branch
        if ssh_key_secret is not None:
            updates["ssh_key_secret"] = ssh_key_secret
        if local_path is not None:
            updates["local_path"] = local_path

        try:
            result = self._collection.find_one_and_update(
                {"_id": config_id},
                {"$set": updates},
                return_document=True,
            )
        except DuplicateKeyError as exc:
            raise ValueError("A Puppet configuration with that name already exists") from exc

        return mappers.document_to_puppet_config(result) if result else None

    def delete(self, config_id: str) -> bool:
        """Delete a Puppet configuration."""
        result = self._collection.delete_one({"_id": config_id})
        return result.deleted_count > 0


# ---------------------------------------------------------------------------
# Bot Platform Account Repository
# ---------------------------------------------------------------------------


class MongoDBBotPlatformAccountRepository:
    """MongoDB repository for bot platform accounts."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["bot_platform_accounts"]

    def get_by_id(self, account_id: int) -> BotPlatformAccountEntity | None:
        """Get account by ID."""
        doc = self._collection.find_one({"_id": account_id})
        return mappers.document_to_bot_platform_account(doc) if doc else None

    def get_by_platform_user(self, platform: str, platform_user_id: str) -> BotPlatformAccountEntity | None:
        """Get account by platform and platform user ID."""
        doc = self._collection.find_one({"platform": platform, "platform_user_id": platform_user_id})
        return mappers.document_to_bot_platform_account(doc) if doc else None

    def get_by_user_id(self, user_id: str, platform: str | None = None) -> list[BotPlatformAccountEntity]:
        """Get all accounts for a user, optionally filtered by platform."""
        query: dict[str, Any] = {"user_id": user_id}
        if platform:
            query["platform"] = platform
        cursor = self._collection.find(query)
        return [mappers.document_to_bot_platform_account(doc) for doc in cursor]

    def get_unverified_by_user_and_platform(
        self, user_id: str, platform: str
    ) -> BotPlatformAccountEntity | None:
        """Get unverified account for a user on a platform."""
        doc = self._collection.find_one({
            "user_id": user_id,
            "platform": platform,
            "verified": False,
        })
        return mappers.document_to_bot_platform_account(doc) if doc else None

    def get_unverified_by_platform_and_code(
        self, platform: str, code: str
    ) -> BotPlatformAccountEntity | None:
        """Get unverified account by platform and verification code."""
        doc = self._collection.find_one({
            "platform": platform,
            "verification_code": code,
            "verified": False,
        })
        return mappers.document_to_bot_platform_account(doc) if doc else None

    def get_verified_by_platform_user(
        self, platform: str, platform_user_id: str
    ) -> BotPlatformAccountEntity | None:
        """Get verified account by platform and platform user ID."""
        doc = self._collection.find_one({
            "platform": platform,
            "platform_user_id": platform_user_id,
            "verified": True,
        })
        return mappers.document_to_bot_platform_account(doc) if doc else None

    def get_by_verification_code(self, code: str) -> BotPlatformAccountEntity | None:
        """Get account by verification code."""
        doc = self._collection.find_one({"verification_code": code})
        return mappers.document_to_bot_platform_account(doc) if doc else None

    def list_all(self, limit: int | None = None) -> list[BotPlatformAccountEntity]:
        """List all accounts."""
        cursor = self._collection.find()
        if limit:
            cursor = cursor.limit(limit)
        return [mappers.document_to_bot_platform_account(doc) for doc in cursor]

    def create(self, entity: BotPlatformAccountEntity) -> BotPlatformAccountEntity:
        """Create a new account."""
        doc = mappers.bot_platform_account_to_document(entity)
        self._collection.insert_one(doc)
        return entity

    def save(self, entity: BotPlatformAccountEntity) -> BotPlatformAccountEntity:
        """Save (upsert) an account."""
        doc = mappers.bot_platform_account_to_document(entity)
        self._collection.replace_one({"_id": entity.id}, doc, upsert=True)
        return entity

    def update(
        self,
        account_id: int,
        *,
        platform_username: str | None = None,
        verified: bool | None = None,
        verification_code: str | None = None,
        verification_expires: datetime | None = None,
    ) -> BotPlatformAccountEntity | None:
        """Update an existing account."""
        updates: dict[str, Any] = {"updated_at": _now_utc()}
        if platform_username is not None:
            updates["platform_username"] = platform_username
        if verified is not None:
            updates["verified"] = verified
        if verification_code is not None:
            updates["verification_code"] = verification_code
        if verification_expires is not None:
            updates["verification_expires"] = verification_expires

        result = self._collection.find_one_and_update(
            {"_id": account_id},
            {"$set": updates},
            return_document=True,
        )
        return mappers.document_to_bot_platform_account(result) if result else None

    def delete(self, account_id: int) -> bool:
        """Delete an account."""
        result = self._collection.delete_one({"_id": account_id})
        return result.deleted_count > 0

    def delete_by_user_id(self, user_id: str, platform: str | None = None) -> int:
        """Delete all accounts for a user."""
        query: dict[str, Any] = {"user_id": user_id}
        if platform:
            query["platform"] = platform
        result = self._collection.delete_many(query)
        return result.deleted_count

    def delete_expired_verifications(self) -> int:
        """Delete accounts with expired verification codes."""
        result = self._collection.delete_many({
            "verified": False,
            "verification_expires": {"$lt": _now_utc()},
        })
        return result.deleted_count

    def get_next_id(self) -> int:
        """Get the next available ID."""
        doc = self._collection.find_one(sort=[("_id", -1)])
        return (doc["_id"] + 1) if doc else 1


# ---------------------------------------------------------------------------
# Bot Conversation Repository
# ---------------------------------------------------------------------------


class MongoDBBotConversationRepository:
    """MongoDB repository for bot conversations."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["bot_conversations"]

    def get_by_id(self, conversation_id: int) -> BotConversationEntity | None:
        """Get conversation by ID."""
        doc = self._collection.find_one({"_id": conversation_id})
        return mappers.document_to_bot_conversation(doc) if doc else None

    def get_by_platform_conversation(
        self, platform: str, platform_conversation_id: str
    ) -> BotConversationEntity | None:
        """Get conversation by platform and platform conversation ID."""
        doc = self._collection.find_one({
            "platform": platform,
            "platform_conversation_id": platform_conversation_id,
        })
        return mappers.document_to_bot_conversation(doc) if doc else None

    def get_by_account_id(self, account_id: int, limit: int | None = None) -> list[BotConversationEntity]:
        """Get conversations for an account."""
        cursor = self._collection.find({"platform_account_id": account_id}).sort("last_message_at", -1)
        if limit:
            cursor = cursor.limit(limit)
        return [mappers.document_to_bot_conversation(doc) for doc in cursor]

    def create(self, entity: BotConversationEntity) -> BotConversationEntity:
        """Create a new conversation."""
        doc = mappers.bot_conversation_to_document(entity)
        self._collection.insert_one(doc)
        return entity

    def save(self, entity: BotConversationEntity) -> BotConversationEntity:
        """Save (upsert) a conversation."""
        doc = mappers.bot_conversation_to_document(entity)
        self._collection.replace_one({"_id": entity.id}, doc, upsert=True)
        return entity

    def update_last_message_at(self, conversation_id: int, timestamp: datetime) -> bool:
        """Update the last message timestamp."""
        result = self._collection.update_one(
            {"_id": conversation_id},
            {"$set": {"last_message_at": timestamp}},
        )
        return result.modified_count > 0

    def delete(self, conversation_id: int) -> bool:
        """Delete a conversation."""
        result = self._collection.delete_one({"_id": conversation_id})
        return result.deleted_count > 0

    def get_next_id(self) -> int:
        """Get the next available ID."""
        doc = self._collection.find_one(sort=[("_id", -1)])
        return (doc["_id"] + 1) if doc else 1


# ---------------------------------------------------------------------------
# Bot Message Repository
# ---------------------------------------------------------------------------


class MongoDBBotMessageRepository:
    """MongoDB repository for bot messages."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["bot_messages"]

    def get_by_id(self, message_id: int) -> BotMessageEntity | None:
        """Get message by ID."""
        doc = self._collection.find_one({"_id": message_id})
        return mappers.document_to_bot_message(doc) if doc else None

    def get_by_conversation_id(
        self, conversation_id: int, limit: int | None = None
    ) -> list[BotMessageEntity]:
        """Get messages for a conversation."""
        cursor = self._collection.find({"conversation_id": conversation_id}).sort("created_at", 1)
        if limit:
            cursor = cursor.limit(limit)
        return [mappers.document_to_bot_message(doc) for doc in cursor]

    def get_recent_for_conversation(
        self, conversation_id: int, limit: int = 10
    ) -> list[BotMessageEntity]:
        """Get recent messages for a conversation (newest first, then reversed)."""
        cursor = self._collection.find({"conversation_id": conversation_id}).sort("created_at", -1).limit(limit)
        messages = [mappers.document_to_bot_message(doc) for doc in cursor]
        return list(reversed(messages))

    def create(self, entity: BotMessageEntity) -> BotMessageEntity:
        """Create a new message."""
        doc = mappers.bot_message_to_document(entity)
        self._collection.insert_one(doc)
        return entity

    def delete_by_conversation_id(self, conversation_id: int) -> int:
        """Delete all messages for a conversation."""
        result = self._collection.delete_many({"conversation_id": conversation_id})
        return result.deleted_count

    def get_next_id(self) -> int:
        """Get the next available ID."""
        doc = self._collection.find_one(sort=[("_id", -1)])
        return (doc["_id"] + 1) if doc else 1


# ---------------------------------------------------------------------------
# Bot Webhook Config Repository
# ---------------------------------------------------------------------------


class MongoDBBotWebhookConfigRepository:
    """MongoDB repository for bot webhook configurations."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["bot_webhook_configs"]

    def get_by_id(self, config_id: int) -> BotWebhookConfigEntity | None:
        """Get config by ID."""
        doc = self._collection.find_one({"_id": config_id})
        return mappers.document_to_bot_webhook_config(doc) if doc else None

    def get_by_platform(self, platform: str) -> BotWebhookConfigEntity | None:
        """Get config by platform."""
        doc = self._collection.find_one({"platform": platform})
        return mappers.document_to_bot_webhook_config(doc) if doc else None

    def list_all(self) -> list[BotWebhookConfigEntity]:
        """List all webhook configs."""
        cursor = self._collection.find()
        return [mappers.document_to_bot_webhook_config(doc) for doc in cursor]

    def save(self, entity: BotWebhookConfigEntity) -> BotWebhookConfigEntity:
        """Save (upsert) a webhook config."""
        doc = mappers.bot_webhook_config_to_document(entity)
        self._collection.replace_one({"_id": entity.id}, doc, upsert=True)
        return entity


__all__ = [
    "MongoDBBotConversationRepository",
    "MongoDBBotMessageRepository",
    "MongoDBBotPlatformAccountRepository",
    "MongoDBBotWebhookConfigRepository",
    "MongoDBChatSessionRepository",
    "MongoDBForemanConfigRepository",
    "MongoDBGlobalAPIKeyRepository",
    "MongoDBPuppetConfigRepository",
    "MongoDBRolePermissionRepository",
    "MongoDBUserAPIKeyRepository",
    "MongoDBUserRepository",
    "MongoDBVCenterConfigRepository",
]
