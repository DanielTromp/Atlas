"""MongoDB index definitions for all collections.

Defines indexes for both application collections (from SQLite) and cache collections (from JSON).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pymongo import ASCENDING, DESCENDING, IndexModel, TEXT
from pymongo.database import Database

from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CollectionIndexes:
    """Index definitions for a single collection."""

    collection: str
    indexes: tuple[IndexModel, ...]


# =============================================================================
# Application Collection Indexes (from SQLite)
# =============================================================================

USERS_INDEXES = CollectionIndexes(
    collection="users",
    indexes=(
        IndexModel([("username", ASCENDING)], unique=True, name="idx_username_unique"),
        IndexModel([("email", ASCENDING)], sparse=True, name="idx_email"),
        IndexModel([("external_subject", ASCENDING)], sparse=True, name="idx_external_subject"),
        IndexModel([("is_active", ASCENDING)], name="idx_is_active"),
        IndexModel([("created_at", DESCENDING)], name="idx_created_at"),
    ),
)

USER_API_KEYS_INDEXES = CollectionIndexes(
    collection="user_api_keys",
    indexes=(
        IndexModel([("user_id", ASCENDING), ("provider", ASCENDING)], unique=True, name="idx_user_provider_unique"),
        IndexModel([("user_id", ASCENDING)], name="idx_user_id"),
    ),
)

GLOBAL_API_KEYS_INDEXES = CollectionIndexes(
    collection="global_api_keys",
    indexes=(
        IndexModel([("provider", ASCENDING)], unique=True, name="idx_provider_unique"),
    ),
)

SECURE_SETTINGS_INDEXES = CollectionIndexes(
    collection="secure_settings",
    indexes=(
        IndexModel([("name", ASCENDING)], unique=True, name="idx_name_unique"),
    ),
)

ROLE_PERMISSIONS_INDEXES = CollectionIndexes(
    collection="role_permissions",
    indexes=(
        IndexModel([("role", ASCENDING)], unique=True, name="idx_role_unique"),
    ),
)

CHAT_SESSIONS_INDEXES = CollectionIndexes(
    collection="chat_sessions",
    indexes=(
        IndexModel([("session_id", ASCENDING)], unique=True, name="idx_session_id_unique"),
        IndexModel([("user_id", ASCENDING)], name="idx_user_id"),
        IndexModel([("updated_at", DESCENDING)], name="idx_updated_at"),
    ),
)

CHAT_MESSAGES_INDEXES = CollectionIndexes(
    collection="chat_messages",
    indexes=(
        IndexModel([("session_id", ASCENDING)], name="idx_session_id"),
        IndexModel([("session_id", ASCENDING), ("created_at", ASCENDING)], name="idx_session_id_created_at"),
    ),
)

VCENTER_CONFIGS_INDEXES = CollectionIndexes(
    collection="vcenter_configs",
    indexes=(
        IndexModel([("name", ASCENDING)], unique=True, name="idx_name_unique"),
    ),
)

FOREMAN_CONFIGS_INDEXES = CollectionIndexes(
    collection="foreman_configs",
    indexes=(
        IndexModel([("name", ASCENDING)], unique=True, name="idx_name_unique"),
    ),
)

PUPPET_CONFIGS_INDEXES = CollectionIndexes(
    collection="puppet_configs",
    indexes=(
        IndexModel([("name", ASCENDING)], unique=True, name="idx_name_unique"),
    ),
)

MODULE_CONFIGS_INDEXES = CollectionIndexes(
    collection="module_configs",
    indexes=(
        IndexModel([("module_name", ASCENDING)], unique=True, name="idx_module_name_unique"),
    ),
)

WORKFLOWS_INDEXES = CollectionIndexes(
    collection="workflows",
    indexes=(
        IndexModel([("name", ASCENDING)], unique=True, name="idx_name_unique"),
        IndexModel([("trigger_type", ASCENDING)], name="idx_trigger_type"),
        IndexModel([("is_active", ASCENDING)], name="idx_is_active"),
    ),
)

WORKFLOW_EXECUTIONS_INDEXES = CollectionIndexes(
    collection="workflow_executions",
    indexes=(
        IndexModel([("workflow_id", ASCENDING)], name="idx_workflow_id"),
        IndexModel([("status", ASCENDING)], name="idx_status"),
        IndexModel([("started_at", DESCENDING)], name="idx_started_at"),
    ),
)

EXECUTION_STEPS_INDEXES = CollectionIndexes(
    collection="execution_steps",
    indexes=(
        IndexModel([("execution_id", ASCENDING)], name="idx_execution_id"),
        IndexModel([("execution_id", ASCENDING), ("created_at", ASCENDING)], name="idx_execution_id_created_at"),
    ),
)

HUMAN_INTERVENTIONS_INDEXES = CollectionIndexes(
    collection="human_interventions",
    indexes=(
        IndexModel([("execution_id", ASCENDING)], name="idx_execution_id"),
        IndexModel([("responded_at", ASCENDING)], sparse=True, name="idx_responded_at"),
    ),
)

SKILLS_INDEXES = CollectionIndexes(
    collection="skills",
    indexes=(
        IndexModel([("name", ASCENDING)], unique=True, name="idx_name_unique"),
        IndexModel([("category", ASCENDING)], sparse=True, name="idx_category"),
        IndexModel([("is_enabled", ASCENDING)], name="idx_is_enabled"),
    ),
)

SKILL_ACTIONS_INDEXES = CollectionIndexes(
    collection="skill_actions",
    indexes=(
        IndexModel([("skill_id", ASCENDING), ("name", ASCENDING)], unique=True, name="idx_skill_action_unique"),
        IndexModel([("skill_id", ASCENDING)], name="idx_skill_id"),
    ),
)

PLAYGROUND_SESSIONS_INDEXES = CollectionIndexes(
    collection="playground_sessions",
    indexes=(
        IndexModel([("user_id", ASCENDING)], name="idx_user_id"),
        IndexModel([("agent_id", ASCENDING)], name="idx_agent_id"),
        IndexModel([("updated_at", DESCENDING)], name="idx_updated_at"),
    ),
)

PLAYGROUND_PRESETS_INDEXES = CollectionIndexes(
    collection="playground_presets",
    indexes=(
        IndexModel([("user_id", ASCENDING), ("name", ASCENDING)], unique=True, name="idx_user_name_unique"),
        IndexModel([("agent_id", ASCENDING)], name="idx_agent_id"),
        IndexModel([("is_shared", ASCENDING)], name="idx_is_shared"),
    ),
)

PLAYGROUND_USAGE_INDEXES = CollectionIndexes(
    collection="playground_usage",
    indexes=(
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="idx_user_id_created_at"),
        IndexModel([("agent_id", ASCENDING), ("created_at", DESCENDING)], name="idx_agent_id_created_at"),
        IndexModel([("session_id", ASCENDING)], name="idx_session_id"),
        IndexModel([("created_at", DESCENDING)], name="idx_created_at"),
    ),
)

AI_ACTIVITY_LOGS_INDEXES = CollectionIndexes(
    collection="ai_activity_logs",
    indexes=(
        IndexModel([("generation_id", ASCENDING)], sparse=True, name="idx_generation_id"),
        IndexModel([("created_at", DESCENDING)], name="idx_created_at"),
        IndexModel([("provider", ASCENDING)], name="idx_provider"),
        IndexModel([("model", ASCENDING)], name="idx_model"),
        IndexModel([("user_id", ASCENDING)], name="idx_user_id"),
        IndexModel([("session_id", ASCENDING)], sparse=True, name="idx_session_id"),
    ),
)

AI_MODEL_CONFIGS_INDEXES = CollectionIndexes(
    collection="ai_model_configs",
    indexes=(
        IndexModel([("provider", ASCENDING), ("model_id", ASCENDING)], unique=True, name="idx_provider_model_unique"),
        IndexModel([("is_active", ASCENDING)], name="idx_is_active"),
    ),
)

BOT_PLATFORM_ACCOUNTS_INDEXES = CollectionIndexes(
    collection="bot_platform_accounts",
    indexes=(
        IndexModel([("platform", ASCENDING), ("platform_user_id", ASCENDING)], unique=True, name="idx_platform_user_unique"),
        IndexModel([("user_id", ASCENDING)], name="idx_user_id"),
    ),
)

BOT_CONVERSATIONS_INDEXES = CollectionIndexes(
    collection="bot_conversations",
    indexes=(
        IndexModel([("platform", ASCENDING), ("platform_conversation_id", ASCENDING)], unique=True, name="idx_platform_conversation_unique"),
        IndexModel([("platform_account_id", ASCENDING)], name="idx_platform_account_id"),
    ),
)

BOT_MESSAGES_INDEXES = CollectionIndexes(
    collection="bot_messages",
    indexes=(
        IndexModel([("conversation_id", ASCENDING)], name="idx_conversation_id"),
        IndexModel([("created_at", DESCENDING)], name="idx_created_at"),
    ),
)

BOT_WEBHOOK_CONFIGS_INDEXES = CollectionIndexes(
    collection="bot_webhook_configs",
    indexes=(
        IndexModel([("platform", ASCENDING)], unique=True, name="idx_platform_unique"),
    ),
)

# =============================================================================
# Cache Collection Indexes (from JSON files)
# =============================================================================

VCENTER_VMS_INDEXES = CollectionIndexes(
    collection="vcenter_vms",
    indexes=(
        IndexModel([("config_id", ASCENDING), ("vm_id", ASCENDING)], unique=True, name="idx_config_vm_unique"),
        IndexModel([("config_id", ASCENDING)], name="idx_config_id"),
        IndexModel([("name", ASCENDING)], name="idx_name"),
        IndexModel([("power_state", ASCENDING)], name="idx_power_state"),
        IndexModel([("ip_addresses", ASCENDING)], name="idx_ip_addresses"),
        IndexModel([("instance_uuid", ASCENDING)], sparse=True, name="idx_instance_uuid"),
        IndexModel([("cluster", ASCENDING)], sparse=True, name="idx_cluster"),
        IndexModel([("datacenter", ASCENDING)], sparse=True, name="idx_datacenter"),
        IndexModel([("name", TEXT), ("guest_host_name", TEXT)], name="idx_text_search"),
    ),
)

COMMVAULT_JOBS_INDEXES = CollectionIndexes(
    collection="commvault_jobs",
    indexes=(
        IndexModel([("client_name", ASCENDING), ("job_id", ASCENDING)], unique=True, name="idx_client_job_unique"),
        IndexModel([("client_name", ASCENDING)], name="idx_client_name"),
        IndexModel([("status", ASCENDING)], name="idx_status"),
        IndexModel([("start_time", DESCENDING)], name="idx_start_time"),
        IndexModel([("job_type", ASCENDING)], sparse=True, name="idx_job_type"),
    ),
)

# All application indexes
APPLICATION_INDEXES: tuple[CollectionIndexes, ...] = (
    USERS_INDEXES,
    USER_API_KEYS_INDEXES,
    GLOBAL_API_KEYS_INDEXES,
    SECURE_SETTINGS_INDEXES,
    ROLE_PERMISSIONS_INDEXES,
    CHAT_SESSIONS_INDEXES,
    CHAT_MESSAGES_INDEXES,
    VCENTER_CONFIGS_INDEXES,
    FOREMAN_CONFIGS_INDEXES,
    PUPPET_CONFIGS_INDEXES,
    MODULE_CONFIGS_INDEXES,
    WORKFLOWS_INDEXES,
    WORKFLOW_EXECUTIONS_INDEXES,
    EXECUTION_STEPS_INDEXES,
    HUMAN_INTERVENTIONS_INDEXES,
    SKILLS_INDEXES,
    SKILL_ACTIONS_INDEXES,
    PLAYGROUND_SESSIONS_INDEXES,
    PLAYGROUND_PRESETS_INDEXES,
    PLAYGROUND_USAGE_INDEXES,
    AI_ACTIVITY_LOGS_INDEXES,
    AI_MODEL_CONFIGS_INDEXES,
    BOT_PLATFORM_ACCOUNTS_INDEXES,
    BOT_CONVERSATIONS_INDEXES,
    BOT_MESSAGES_INDEXES,
    BOT_WEBHOOK_CONFIGS_INDEXES,
)

# All cache indexes
CACHE_INDEXES: tuple[CollectionIndexes, ...] = (
    VCENTER_VMS_INDEXES,
    COMMVAULT_JOBS_INDEXES,
)


def create_indexes(db: Database, indexes: tuple[CollectionIndexes, ...]) -> dict[str, list[str]]:
    """Create indexes for the specified collections.

    Args:
        db: MongoDB database instance.
        indexes: Tuple of CollectionIndexes to create.

    Returns:
        Dict mapping collection names to lists of created index names.
    """
    results: dict[str, list[str]] = {}

    for collection_indexes in indexes:
        collection = db[collection_indexes.collection]
        created: list[str] = []

        for index in collection_indexes.indexes:
            try:
                index_name = collection.create_indexes([index])[0]
                created.append(index_name)
            except Exception as e:
                logger.warning(
                    "Failed to create index on %s: %s",
                    collection_indexes.collection,
                    e,
                )

        results[collection_indexes.collection] = created
        if created:
            logger.debug(
                "Created %d indexes on %s: %s",
                len(created),
                collection_indexes.collection,
                ", ".join(created),
            )

    return results


def create_application_indexes(db: Database) -> dict[str, list[str]]:
    """Create all indexes for application collections.

    Args:
        db: MongoDB database instance (atlas).

    Returns:
        Dict mapping collection names to lists of created index names.
    """
    logger.info("Creating application indexes on database %s", db.name)
    return create_indexes(db, APPLICATION_INDEXES)


def create_cache_indexes(db: Database) -> dict[str, list[str]]:
    """Create all indexes for cache collections.

    Args:
        db: MongoDB database instance (atlas_cache).

    Returns:
        Dict mapping collection names to lists of created index names.
    """
    logger.info("Creating cache indexes on database %s", db.name)
    return create_indexes(db, CACHE_INDEXES)


async def create_indexes_async(db: Any, indexes: tuple[CollectionIndexes, ...]) -> dict[str, list[str]]:
    """Create indexes asynchronously for the specified collections.

    Args:
        db: Motor async database instance.
        indexes: Tuple of CollectionIndexes to create.

    Returns:
        Dict mapping collection names to lists of created index names.
    """
    results: dict[str, list[str]] = {}

    for collection_indexes in indexes:
        collection = db[collection_indexes.collection]
        created: list[str] = []

        for index in collection_indexes.indexes:
            try:
                index_names = await collection.create_indexes([index])
                created.extend(index_names)
            except Exception as e:
                logger.warning(
                    "Failed to create async index on %s: %s",
                    collection_indexes.collection,
                    e,
                )

        results[collection_indexes.collection] = created
        if created:
            logger.debug(
                "Created %d async indexes on %s: %s",
                len(created),
                collection_indexes.collection,
                ", ".join(created),
            )

    return results


async def create_application_indexes_async(db: Any) -> dict[str, list[str]]:
    """Create all indexes for application collections asynchronously.

    Args:
        db: Motor async database instance (atlas).

    Returns:
        Dict mapping collection names to lists of created index names.
    """
    logger.info("Creating application indexes (async) on database %s", db.name)
    return await create_indexes_async(db, APPLICATION_INDEXES)


async def create_cache_indexes_async(db: Any) -> dict[str, list[str]]:
    """Create all indexes for cache collections asynchronously.

    Args:
        db: Motor async database instance (atlas_cache).

    Returns:
        Dict mapping collection names to lists of created index names.
    """
    logger.info("Creating cache indexes (async) on database %s", db.name)
    return await create_indexes_async(db, CACHE_INDEXES)


__all__ = [
    "APPLICATION_INDEXES",
    "CACHE_INDEXES",
    "CollectionIndexes",
    "create_application_indexes",
    "create_application_indexes_async",
    "create_cache_indexes",
    "create_cache_indexes_async",
    "create_indexes",
    "create_indexes_async",
]
