"""Conversion helpers between ORM models and domain entities."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from infrastructure_atlas.db import models
from infrastructure_atlas.domain.entities import (
    ChatMessageEntity,
    ChatSessionEntity,
    ForemanConfigEntity,
    GlobalAPIKeyEntity,
    RolePermissionEntity,
    UserAPIKeyEntity,
    UserEntity,
    VCenterConfigEntity,
)


def user_to_entity(record: models.User) -> UserEntity:
    return UserEntity(
        id=record.id,
        username=record.username,
        display_name=record.display_name,
        email=record.email,
        role=record.role,
        permissions=frozenset(),
        is_active=record.is_active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def user_api_key_to_entity(record: models.UserAPIKey) -> UserAPIKeyEntity:
    return UserAPIKeyEntity(
        id=record.id,
        user_id=record.user_id,
        provider=record.provider,
        label=record.label,
        secret=record.secret,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def global_api_key_to_entity(record: models.GlobalAPIKey) -> GlobalAPIKeyEntity:
    return GlobalAPIKeyEntity(
        id=record.id,
        provider=record.provider,
        label=record.label,
        secret=record.secret,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def chat_session_to_entity(record: models.ChatSession) -> ChatSessionEntity:
    return ChatSessionEntity(
        id=record.id,
        session_id=record.session_id,
        user_id=record.user_id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def chat_message_to_entity(record: models.ChatMessage) -> ChatMessageEntity:
    return ChatMessageEntity(
        id=record.id,
        session_id=record.session_id,
        role=record.role,
        content=record.content,
        created_at=record.created_at,
    )


def iter_chat_messages(records: Iterable[models.ChatMessage]) -> Iterator[ChatMessageEntity]:
    for record in records:
        yield chat_message_to_entity(record)


def role_permission_to_entity(record: models.RolePermission) -> RolePermissionEntity:
    return RolePermissionEntity(
        role=record.role,
        label=record.label,
        description=record.description,
        permissions=frozenset(record.permissions or []),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def vcenter_config_to_entity(record: models.VCenterConfig) -> VCenterConfigEntity:
    return VCenterConfigEntity(
        id=record.id,
        name=record.name,
        base_url=record.base_url,
        username=record.username,
        verify_ssl=record.verify_ssl,
        is_esxi=record.is_esxi,
        password_secret=record.password_secret,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def foreman_config_to_entity(record: models.ForemanConfig) -> ForemanConfigEntity:
    return ForemanConfigEntity(
        id=record.id,
        name=record.name,
        base_url=record.base_url,
        username=record.username,
        token_secret=record.token_secret,
        verify_ssl=record.verify_ssl,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
