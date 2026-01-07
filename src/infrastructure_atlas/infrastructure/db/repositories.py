"""SQLAlchemy-backed repository implementations."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from infrastructure_atlas.db import models
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


class SqlAlchemyUserRepository(UserRepository):
    """Read-only user repository backed by SQLAlchemy."""

    def __init__(self, session: Session):
        self._session = session

    def get_by_id(self, user_id: str):
        record = self._session.get(models.User, user_id)
        return mappers.user_to_entity(record) if record else None

    def get_by_username(self, username: str):
        stmt = select(models.User).where(models.User.username == username)
        record = self._session.execute(stmt).scalar_one_or_none()
        return mappers.user_to_entity(record) if record else None

    def list_all(self):
        stmt = select(models.User).order_by(models.User.created_at.asc())
        records = self._session.execute(stmt).scalars().all()
        return [mappers.user_to_entity(record) for record in records]


class SqlAlchemyUserAPIKeyRepository(UserAPIKeyRepository):
    """Repository for user-scoped API keys."""

    def __init__(self, session: Session):
        self._session = session

    def list_for_user(self, user_id: str):
        stmt = select(models.UserAPIKey).where(models.UserAPIKey.user_id == user_id)
        records = self._session.execute(stmt).scalars().all()
        return [mappers.user_api_key_to_entity(record) for record in records]

    def get(self, user_id: str, provider: str):
        stmt = select(models.UserAPIKey).where(
            models.UserAPIKey.user_id == user_id,
            models.UserAPIKey.provider == provider,
        )
        record = self._session.execute(stmt).scalar_one_or_none()
        return mappers.user_api_key_to_entity(record) if record else None


class SqlAlchemyGlobalAPIKeyRepository(GlobalAPIKeyRepository):
    """Repository for globally-scoped API keys."""

    def __init__(self, session: Session):
        self._session = session

    def list_all(self):
        stmt = select(models.GlobalAPIKey).order_by(models.GlobalAPIKey.provider.asc())
        records = self._session.execute(stmt).scalars().all()
        return [mappers.global_api_key_to_entity(record) for record in records]

    def get(self, provider: str):
        stmt = select(models.GlobalAPIKey).where(models.GlobalAPIKey.provider == provider)
        record = self._session.execute(stmt).scalar_one_or_none()
        return mappers.global_api_key_to_entity(record) if record else None


class SqlAlchemyChatSessionRepository(ChatSessionRepository):
    """Repository for chat sessions and messages."""

    def __init__(self, session: Session):
        self._session = session

    def list_sessions(self, user_id: str | None = None):
        stmt = select(models.ChatSession).order_by(models.ChatSession.updated_at.desc())
        if user_id:
            stmt = stmt.where(models.ChatSession.user_id == user_id)
        records = self._session.execute(stmt).scalars().all()
        return [mappers.chat_session_to_entity(record) for record in records]

    def get_session(self, session_id: str):
        stmt = select(models.ChatSession).where(models.ChatSession.session_id == session_id)
        record = self._session.execute(stmt).scalar_one_or_none()
        return mappers.chat_session_to_entity(record) if record else None

    def get_messages(self, session_id: str):
        stmt = (
            select(models.ChatMessage)
            .where(models.ChatMessage.session_id == session_id)
            .order_by(models.ChatMessage.created_at.asc())
        )
        records = self._session.execute(stmt).scalars().all()
        return [mappers.chat_message_to_entity(record) for record in records]

    def iter_messages(self, session_id: str):
        stmt = (
            select(models.ChatMessage)
            .where(models.ChatMessage.session_id == session_id)
            .order_by(models.ChatMessage.created_at.asc())
        )
        result: Iterable[models.ChatMessage] = self._session.execute(stmt).scalars()
        return mappers.iter_chat_messages(result)


class SqlAlchemyRolePermissionRepository(RolePermissionRepository):
    """Repository for role permission definitions."""

    def __init__(self, session: Session):
        self._session = session

    def list_all(self):
        stmt = select(models.RolePermission).order_by(models.RolePermission.role.asc())
        records = self._session.execute(stmt).scalars().all()
        return [mappers.role_permission_to_entity(record) for record in records]

    def get(self, role: str):
        record = self._session.get(models.RolePermission, role)
        return mappers.role_permission_to_entity(record) if record else None

    def upsert(self, role: str, label: str, description: str | None, permissions):
        label_clean = (label or role).strip() or role
        description_clean = description.strip() if isinstance(description, str) and description.strip() else None
        cleaned_set: set[str] = set()
        for perm in permissions:
            if perm is None:
                continue
            text = str(perm).strip()
            if not text:
                continue
            cleaned_set.add(text)
        cleaned = sorted(cleaned_set)
        record = self._session.get(models.RolePermission, role)
        if record is None:
            record = models.RolePermission(
                role=role,
                label=label_clean,
                description=description_clean,
                permissions=cleaned,
            )
            self._session.add(record)
        else:
            record.label = label_clean
            record.description = description_clean
            record.permissions = cleaned
        self._session.commit()
        self._session.refresh(record)
        return mappers.role_permission_to_entity(record)


class SqlAlchemyVCenterConfigRepository(VCenterConfigRepository):
    """Repository for stored vCenter configuration records."""

    def __init__(self, session: Session):
        self._session = session

    def list_all(self):
        stmt = select(models.VCenterConfig).order_by(models.VCenterConfig.name.asc())
        records = self._session.execute(stmt).scalars().all()
        return [mappers.vcenter_config_to_entity(record) for record in records]

    def get(self, config_id: str):
        record = self._session.get(models.VCenterConfig, config_id)
        return mappers.vcenter_config_to_entity(record) if record else None

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
    ):
        record = models.VCenterConfig(
            id=config_id,
            name=name,
            base_url=base_url,
            username=username,
            password_secret=password_secret,
            verify_ssl=verify_ssl,
            is_esxi=is_esxi,
        )
        self._session.add(record)
        self._session.flush()
        self._session.refresh(record)
        return mappers.vcenter_config_to_entity(record)

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
    ):
        record = self._session.get(models.VCenterConfig, config_id)
        if record is None:
            return None
        if name is not None:
            record.name = name
        if base_url is not None:
            record.base_url = base_url
        if username is not None:
            record.username = username
        if verify_ssl is not None:
            record.verify_ssl = verify_ssl
        if password_secret is not None:
            record.password_secret = password_secret
        if is_esxi is not None:
            record.is_esxi = is_esxi
        self._session.add(record)
        self._session.flush()
        self._session.refresh(record)
        return mappers.vcenter_config_to_entity(record)

    def delete(self, config_id: str):
        record = self._session.get(models.VCenterConfig, config_id)
        if record is None:
            return False
        self._session.delete(record)
        self._session.flush()
        return True


class SqlAlchemyForemanConfigRepository(ForemanConfigRepository):
    """Repository for stored Foreman configuration records."""

    def __init__(self, session: Session):
        self._session = session

    def list_all(self):
        stmt = select(models.ForemanConfig).order_by(models.ForemanConfig.name.asc())
        records = self._session.execute(stmt).scalars().all()
        return [mappers.foreman_config_to_entity(record) for record in records]

    def get(self, config_id: str):
        record = self._session.get(models.ForemanConfig, config_id)
        return mappers.foreman_config_to_entity(record) if record else None

    def create(  # noqa: PLR0913
        self,
        *,
        config_id: str | None,
        name: str,
        base_url: str,
        username: str,
        token_secret: str,
        verify_ssl: bool,
    ):
        record = models.ForemanConfig(
            id=config_id,
            name=name,
            base_url=base_url,
            username=username,
            token_secret=token_secret,
            verify_ssl=verify_ssl,
        )
        self._session.add(record)
        self._session.flush()
        self._session.refresh(record)
        return mappers.foreman_config_to_entity(record)

    def update(  # noqa: PLR0913
        self,
        config_id: str,
        *,
        name: str | None = None,
        base_url: str | None = None,
        username: str | None = None,
        verify_ssl: bool | None = None,
        token_secret: str | None = None,
    ):
        record = self._session.get(models.ForemanConfig, config_id)
        if record is None:
            return None
        if name is not None:
            record.name = name
        if base_url is not None:
            record.base_url = base_url
        if username is not None:
            record.username = username
        if verify_ssl is not None:
            record.verify_ssl = verify_ssl
        if token_secret is not None:
            record.token_secret = token_secret
        self._session.add(record)
        self._session.flush()
        self._session.refresh(record)
        return mappers.foreman_config_to_entity(record)

    def delete(self, config_id: str):
        record = self._session.get(models.ForemanConfig, config_id)
        if record is None:
            return False
        self._session.delete(record)
        self._session.flush()
        return True


__all__ = [
    "SqlAlchemyChatSessionRepository",
    "SqlAlchemyForemanConfigRepository",
    "SqlAlchemyGlobalAPIKeyRepository",
    "SqlAlchemyRolePermissionRepository",
    "SqlAlchemyUserAPIKeyRepository",
    "SqlAlchemyUserRepository",
    "SqlAlchemyVCenterConfigRepository",
]
