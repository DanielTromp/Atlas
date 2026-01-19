"""Migrate data from SQLite to MongoDB.

This migration reads all data from the SQLite database and inserts it
into MongoDB collections.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pymongo.database import Database
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

version = 2
description = "Migrate data from SQLite to MongoDB"


def _get_sqlite_path() -> Path | None:
    """Resolve the SQLite database path from environment or default."""
    db_url = os.getenv("ATLAS_DB_URL", "")
    if db_url.startswith("sqlite:///"):
        return Path(db_url.replace("sqlite:///", ""))

    # Default location
    from infrastructure_atlas.env import project_root
    default_path = project_root() / "data" / "atlas.sqlite3"
    if default_path.exists():
        return default_path

    # Try alternate name
    alt_path = project_root() / "data" / "atlas.db"
    if alt_path.exists():
        return alt_path

    return None


def _convert_datetime(value: Any) -> datetime | None:
    """Convert a value to datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            return None
    return None


def _migrate_users(session: Session, app_db: Database) -> int:
    """Migrate users table."""
    result = session.execute(text("SELECT * FROM users"))
    rows = result.mappings().all()

    if not rows:
        return 0

    documents = []
    for row in rows:
        doc = {
            "_id": row["id"],
            "username": row["username"],
            "display_name": row.get("display_name"),
            "email": row.get("email"),
            "role": row.get("role", "member"),
            "password_hash": row.get("password_hash"),
            "is_active": bool(row.get("is_active", True)),
            "external_provider": row.get("external_provider"),
            "external_subject": row.get("external_subject"),
            "system_username": row.get("system_username"),
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["users"].insert_many(documents)
    return len(documents)


def _migrate_user_api_keys(session: Session, app_db: Database) -> int:
    """Migrate user_api_keys table."""
    result = session.execute(text("SELECT * FROM user_api_keys"))
    rows = result.mappings().all()

    if not rows:
        return 0

    documents = []
    for row in rows:
        doc = {
            "_id": row["id"],
            "user_id": row["user_id"],
            "provider": row["provider"],
            "label": row.get("label"),
            "secret": row["secret"],
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["user_api_keys"].insert_many(documents)
    return len(documents)


def _migrate_global_api_keys(session: Session, app_db: Database) -> int:
    """Migrate global_api_keys table."""
    result = session.execute(text("SELECT * FROM global_api_keys"))
    rows = result.mappings().all()

    if not rows:
        return 0

    documents = []
    for row in rows:
        doc = {
            "_id": row["id"],
            "provider": row["provider"],
            "label": row.get("label"),
            "secret": row["secret"],
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["global_api_keys"].insert_many(documents)
    return len(documents)


def _migrate_secure_settings(session: Session, app_db: Database) -> int:
    """Migrate secure_settings table."""
    result = session.execute(text("SELECT * FROM secure_settings"))
    rows = result.mappings().all()

    if not rows:
        return 0

    documents = []
    for row in rows:
        doc = {
            "_id": row["name"],
            "name": row["name"],
            "encrypted_value": row["encrypted_value"],
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["secure_settings"].insert_many(documents)
    return len(documents)


def _migrate_role_permissions(session: Session, app_db: Database) -> int:
    """Migrate role_permissions table."""
    result = session.execute(text("SELECT * FROM role_permissions"))
    rows = result.mappings().all()

    if not rows:
        return 0

    import json

    documents = []
    for row in rows:
        permissions = row.get("permissions")
        if isinstance(permissions, str):
            try:
                permissions = json.loads(permissions)
            except (json.JSONDecodeError, ValueError):
                permissions = []

        doc = {
            "_id": row["role"],
            "role": row["role"],
            "label": row.get("label", row["role"]),
            "description": row.get("description"),
            "permissions": permissions or [],
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["role_permissions"].insert_many(documents)
    return len(documents)


def _migrate_chat_sessions(session: Session, app_db: Database) -> int:
    """Migrate chat_sessions table."""
    result = session.execute(text("SELECT * FROM chat_sessions"))
    rows = result.mappings().all()

    if not rows:
        return 0

    import json

    documents = []
    for row in rows:
        context_vars = row.get("context_variables")
        if isinstance(context_vars, str):
            try:
                context_vars = json.loads(context_vars)
            except (json.JSONDecodeError, ValueError):
                context_vars = {}

        doc = {
            "_id": row["id"],
            "session_id": row["session_id"],
            "user_id": row.get("user_id"),
            "title": row.get("title", "New AI Chat"),
            "context_variables": context_vars or {},
            "agent_config_id": row.get("agent_config_id"),
            "provider_type": row.get("provider_type"),
            "model": row.get("model"),
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["chat_sessions"].insert_many(documents)
    return len(documents)


def _migrate_chat_messages(session: Session, app_db: Database) -> int:
    """Migrate chat_messages table."""
    result = session.execute(text("SELECT * FROM chat_messages"))
    rows = result.mappings().all()

    if not rows:
        return 0

    import json

    documents = []
    for row in rows:
        metadata = row.get("metadata_json")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, ValueError):
                metadata = None

        doc = {
            "_id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "message_type": row.get("message_type"),
            "tool_call_id": row.get("tool_call_id"),
            "tool_name": row.get("tool_name"),
            "metadata_json": metadata,
            "created_at": _convert_datetime(row.get("created_at")),
        }
        documents.append(doc)

    app_db["chat_messages"].insert_many(documents)
    return len(documents)


def _migrate_vcenter_configs(session: Session, app_db: Database) -> int:
    """Migrate vcenter_configs table."""
    result = session.execute(text("SELECT * FROM vcenter_configs"))
    rows = result.mappings().all()

    if not rows:
        return 0

    documents = []
    for row in rows:
        doc = {
            "_id": row["id"],
            "name": row["name"],
            "base_url": row["base_url"],
            "username": row["username"],
            "password_secret": row["password_secret"],
            "verify_ssl": bool(row.get("verify_ssl", True)),
            "is_esxi": bool(row.get("is_esxi", False)),
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["vcenter_configs"].insert_many(documents)
    return len(documents)


def _migrate_foreman_configs(session: Session, app_db: Database) -> int:
    """Migrate foreman_configs table."""
    result = session.execute(text("SELECT * FROM foreman_configs"))
    rows = result.mappings().all()

    if not rows:
        return 0

    documents = []
    for row in rows:
        doc = {
            "_id": row["id"],
            "name": row["name"],
            "base_url": row["base_url"],
            "username": row["username"],
            "token_secret": row["token_secret"],
            "verify_ssl": bool(row.get("verify_ssl", True)),
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["foreman_configs"].insert_many(documents)
    return len(documents)


def _migrate_module_configs(session: Session, app_db: Database) -> int:
    """Migrate module_configs table."""
    result = session.execute(text("SELECT * FROM module_configs"))
    rows = result.mappings().all()

    if not rows:
        return 0

    import json

    documents = []
    for row in rows:
        config_json = row.get("config_json")
        if isinstance(config_json, str):
            try:
                config_json = json.loads(config_json)
            except (json.JSONDecodeError, ValueError):
                config_json = {}

        doc = {
            "_id": row["module_name"],
            "module_name": row["module_name"],
            "enabled": bool(row.get("enabled", True)),
            "config_json": config_json or {},
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["module_configs"].insert_many(documents)
    return len(documents)


def _migrate_playground_sessions(session: Session, app_db: Database) -> int:
    """Migrate playground_sessions table."""
    result = session.execute(text("SELECT * FROM playground_sessions"))
    rows = result.mappings().all()

    if not rows:
        return 0

    import json

    documents = []
    for row in rows:
        state = row.get("state")
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except (json.JSONDecodeError, ValueError):
                state = {}

        config_override = row.get("config_override")
        if isinstance(config_override, str):
            try:
                config_override = json.loads(config_override)
            except (json.JSONDecodeError, ValueError):
                config_override = {}

        messages = row.get("messages")
        if isinstance(messages, str):
            try:
                messages = json.loads(messages)
            except (json.JSONDecodeError, ValueError):
                messages = []

        doc = {
            "_id": row["id"],
            "agent_id": row["agent_id"],
            "user_id": row.get("user_id"),
            "state": state or {},
            "config_override": config_override or {},
            "messages": messages or [],
            "total_tokens": row.get("total_tokens", 0),
            "total_cost_usd": row.get("total_cost_usd"),
            "client": row.get("client", "web"),
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["playground_sessions"].insert_many(documents)
    return len(documents)


def _migrate_playground_usage(session: Session, app_db: Database) -> int:
    """Migrate playground_usage table."""
    result = session.execute(text("SELECT * FROM playground_usage"))
    rows = result.mappings().all()

    if not rows:
        return 0

    import json

    documents = []
    for row in rows:
        tool_calls = row.get("tool_calls")
        if isinstance(tool_calls, str):
            try:
                tool_calls = json.loads(tool_calls)
            except (json.JSONDecodeError, ValueError):
                tool_calls = None

        doc = {
            "_id": row["id"],
            "user_id": row.get("user_id"),
            "username": row.get("username"),
            "session_id": row["session_id"],
            "agent_id": row["agent_id"],
            "model": row["model"],
            "user_message": row["user_message"],
            "assistant_message": row.get("assistant_message"),
            "input_tokens": row.get("input_tokens", 0),
            "output_tokens": row.get("output_tokens", 0),
            "total_tokens": row.get("total_tokens", 0),
            "cost_usd": row.get("cost_usd", 0.0),
            "tool_calls": tool_calls,
            "duration_ms": row.get("duration_ms"),
            "error": row.get("error"),
            "client": row.get("client", "web"),
            "created_at": _convert_datetime(row.get("created_at")),
        }
        documents.append(doc)

    app_db["playground_usage"].insert_many(documents)
    return len(documents)


def _migrate_playground_presets(session: Session, app_db: Database) -> int:
    """Migrate playground_presets table."""
    result = session.execute(text("SELECT * FROM playground_presets"))
    rows = result.mappings().all()

    if not rows:
        return 0

    import json

    documents = []
    for row in rows:
        config = row.get("config")
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (json.JSONDecodeError, ValueError):
                config = {}

        doc = {
            "_id": row["id"],
            "name": row["name"],
            "description": row.get("description"),
            "agent_id": row["agent_id"],
            "config": config or {},
            "user_id": row.get("user_id"),
            "is_shared": bool(row.get("is_shared", False)),
            "is_default": bool(row.get("is_default", False)),
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["playground_presets"].insert_many(documents)
    return len(documents)


def _migrate_puppet_configs(session: Session, app_db: Database) -> int:
    """Migrate puppet_configs table."""
    result = session.execute(text("SELECT * FROM puppet_configs"))
    rows = result.mappings().all()

    if not rows:
        return 0

    documents = []
    for row in rows:
        doc = {
            "_id": row["id"],
            "name": row["name"],
            "remote_url": row["remote_url"],
            "branch": row.get("branch", "production"),
            "ssh_key_secret": row.get("ssh_key_secret"),
            "local_path": row.get("local_path"),
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["puppet_configs"].insert_many(documents)
    return len(documents)


def _migrate_ai_activity_logs(session: Session, app_db: Database) -> int:
    """Migrate ai_activity_logs table."""
    result = session.execute(text("SELECT * FROM ai_activity_logs"))
    rows = result.mappings().all()

    if not rows:
        return 0

    documents = []
    for row in rows:
        doc = {
            "_id": row["id"],
            "generation_id": row.get("generation_id"),
            "provider": row["provider"],
            "model": row["model"],
            "model_provider": row.get("model_provider"),
            "tokens_prompt": row.get("tokens_prompt", 0),
            "tokens_completion": row.get("tokens_completion", 0),
            "tokens_reasoning": row.get("tokens_reasoning", 0),
            "tokens_total": row.get("tokens_total", 0),
            "cost_usd": row.get("cost_usd", 0.0),
            "generation_time_ms": row.get("generation_time_ms"),
            "time_to_first_token_ms": row.get("time_to_first_token_ms"),
            "tokens_per_second": row.get("tokens_per_second"),
            "streamed": bool(row.get("streamed", False)),
            "finish_reason": row.get("finish_reason"),
            "cancelled": bool(row.get("cancelled", False)),
            "user_id": row.get("user_id"),
            "session_id": row.get("session_id"),
            "app_name": row.get("app_name"),
            "created_at": _convert_datetime(row.get("created_at")),
        }
        documents.append(doc)

    app_db["ai_activity_logs"].insert_many(documents)
    return len(documents)


def _migrate_bot_platform_accounts(session: Session, app_db: Database) -> int:
    """Migrate bot_platform_accounts table."""
    result = session.execute(text("SELECT * FROM bot_platform_accounts"))
    rows = result.mappings().all()

    if not rows:
        return 0

    documents = []
    for row in rows:
        doc = {
            "_id": row["id"],
            "user_id": row["user_id"],
            "platform": row["platform"],
            "platform_user_id": row["platform_user_id"],
            "platform_username": row.get("platform_username"),
            "verified": bool(row.get("verified", False)),
            "verification_code": row.get("verification_code"),
            "verification_expires": _convert_datetime(row.get("verification_expires")),
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["bot_platform_accounts"].insert_many(documents)
    return len(documents)


def _migrate_bot_conversations(session: Session, app_db: Database) -> int:
    """Migrate bot_conversations table."""
    result = session.execute(text("SELECT * FROM bot_conversations"))
    rows = result.mappings().all()

    if not rows:
        return 0

    documents = []
    for row in rows:
        doc = {
            "_id": row["id"],
            "platform": row["platform"],
            "platform_conversation_id": row["platform_conversation_id"],
            "platform_account_id": row["platform_account_id"],
            "agent_id": row.get("agent_id"),
            "session_id": row.get("session_id"),
            "created_at": _convert_datetime(row.get("created_at")),
            "last_message_at": _convert_datetime(row.get("last_message_at")),
        }
        documents.append(doc)

    app_db["bot_conversations"].insert_many(documents)
    return len(documents)


def _migrate_bot_messages(session: Session, app_db: Database) -> int:
    """Migrate bot_messages table."""
    result = session.execute(text("SELECT * FROM bot_messages"))
    rows = result.mappings().all()

    if not rows:
        return 0

    import json

    documents = []
    for row in rows:
        tool_calls = row.get("tool_calls")
        if isinstance(tool_calls, str):
            try:
                tool_calls = json.loads(tool_calls)
            except (json.JSONDecodeError, ValueError):
                tool_calls = None

        doc = {
            "_id": row["id"],
            "conversation_id": row["conversation_id"],
            "direction": row["direction"],
            "content": row["content"],
            "platform_message_id": row.get("platform_message_id"),
            "agent_id": row.get("agent_id"),
            "tool_calls": tool_calls,
            "input_tokens": row.get("input_tokens", 0),
            "output_tokens": row.get("output_tokens", 0),
            "cost_usd": row.get("cost_usd", 0.0),
            "duration_ms": row.get("duration_ms"),
            "error": row.get("error"),
            "created_at": _convert_datetime(row.get("created_at")),
        }
        documents.append(doc)

    app_db["bot_messages"].insert_many(documents)
    return len(documents)


def _migrate_bot_webhook_configs(session: Session, app_db: Database) -> int:
    """Migrate bot_webhook_configs table."""
    result = session.execute(text("SELECT * FROM bot_webhook_configs"))
    rows = result.mappings().all()

    if not rows:
        return 0

    import json

    documents = []
    for row in rows:
        extra_config = row.get("extra_config")
        if isinstance(extra_config, str):
            try:
                extra_config = json.loads(extra_config)
            except (json.JSONDecodeError, ValueError):
                extra_config = None

        doc = {
            "_id": row["id"],
            "platform": row["platform"],
            "enabled": bool(row.get("enabled", False)),
            "webhook_secret": row.get("webhook_secret"),
            "bot_token_secret": row["bot_token_secret"],
            "extra_config": extra_config,
            "created_at": _convert_datetime(row.get("created_at")),
            "updated_at": _convert_datetime(row.get("updated_at")),
        }
        documents.append(doc)

    app_db["bot_webhook_configs"].insert_many(documents)
    return len(documents)


def _table_exists(session: Session, table_name: str) -> bool:
    """Check if a table exists in SQLite."""
    result = session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name}
    )
    return result.scalar() is not None


def upgrade(app_db: Database, cache_db: Database) -> dict[str, Any]:
    """Run the upgrade migration.

    Args:
        app_db: The main application database.
        cache_db: The cache database.

    Returns:
        Dict with migration results/stats.
    """
    results: dict[str, Any] = {
        "tables_migrated": {},
        "total_records": 0,
        "sqlite_path": None,
        "skipped_tables": [],
    }

    sqlite_path = _get_sqlite_path()
    if sqlite_path is None or not sqlite_path.exists():
        logger.info("SQLite database not found, skipping migration")
        results["status"] = "skipped"
        results["reason"] = "SQLite database not found"
        return results

    results["sqlite_path"] = str(sqlite_path)
    logger.info("Migrating data from SQLite: %s", sqlite_path)

    engine = create_engine(f"sqlite:///{sqlite_path}")

    # Migration functions for each table
    migrations = [
        ("users", _migrate_users),
        ("user_api_keys", _migrate_user_api_keys),
        ("global_api_keys", _migrate_global_api_keys),
        ("secure_settings", _migrate_secure_settings),
        ("role_permissions", _migrate_role_permissions),
        ("chat_sessions", _migrate_chat_sessions),
        ("chat_messages", _migrate_chat_messages),
        ("vcenter_configs", _migrate_vcenter_configs),
        ("foreman_configs", _migrate_foreman_configs),
        ("module_configs", _migrate_module_configs),
        ("playground_sessions", _migrate_playground_sessions),
        ("playground_usage", _migrate_playground_usage),
        ("playground_presets", _migrate_playground_presets),
        ("puppet_configs", _migrate_puppet_configs),
        ("ai_activity_logs", _migrate_ai_activity_logs),
        ("bot_platform_accounts", _migrate_bot_platform_accounts),
        ("bot_conversations", _migrate_bot_conversations),
        ("bot_messages", _migrate_bot_messages),
        ("bot_webhook_configs", _migrate_bot_webhook_configs),
    ]

    with Session(engine) as session:
        for table_name, migrate_func in migrations:
            if not _table_exists(session, table_name):
                logger.debug("Table %s does not exist, skipping", table_name)
                results["skipped_tables"].append(table_name)
                continue

            try:
                count = migrate_func(session, app_db)
                results["tables_migrated"][table_name] = count
                results["total_records"] += count
                logger.info("Migrated %d records from %s", count, table_name)
            except Exception as e:
                logger.warning("Failed to migrate table %s: %s", table_name, e)
                results["tables_migrated"][table_name] = f"error: {e}"

    results["status"] = "completed"
    return results


def downgrade(app_db: Database, cache_db: Database) -> dict[str, Any]:
    """Rollback the migration by clearing migrated collections.

    Note: This does not restore the SQLite database - it only clears
    the MongoDB collections that were populated by this migration.

    Args:
        app_db: The main application database.
        cache_db: The cache database.

    Returns:
        Dict with rollback results.
    """
    collections = [
        "users",
        "user_api_keys",
        "global_api_keys",
        "secure_settings",
        "role_permissions",
        "chat_sessions",
        "chat_messages",
        "vcenter_configs",
        "foreman_configs",
        "module_configs",
        "playground_sessions",
        "playground_usage",
        "playground_presets",
        "puppet_configs",
        "ai_activity_logs",
        "bot_platform_accounts",
        "bot_conversations",
        "bot_messages",
        "bot_webhook_configs",
    ]

    results: dict[str, Any] = {
        "collections_cleared": {},
    }

    for collection_name in collections:
        try:
            result = app_db[collection_name].delete_many({})
            results["collections_cleared"][collection_name] = result.deleted_count
        except Exception as e:
            results["collections_cleared"][collection_name] = f"error: {e}"

    return results
