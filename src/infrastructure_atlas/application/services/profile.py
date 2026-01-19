"""Profile management service orchestrating user operations."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


class ProfileServiceProtocol(Protocol):
    """Protocol for profile services."""

    def update_profile(self, user: Any, display_name: str | None, email: str | None) -> Any:
        ...

    def change_password(self, user: Any, new_password_hash: str) -> None:
        ...

    def list_api_keys(self, user_id: str) -> list[Any]:
        ...

    def save_api_key(self, user: Any, provider: str, secret: str, label: str | None) -> Any:
        ...

    def delete_api_key(self, user: Any, provider: str) -> None:
        ...


@dataclass(slots=True)
class ProfileService:
    """SQLAlchemy-based profile service."""

    session: Any
    user_service: Any

    def update_profile(self, user: Any, display_name: str | None, email: str | None):
        from infrastructure_atlas.infrastructure.db import mappers

        user.display_name = display_name
        user.email = email
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return mappers.user_to_entity(user)

    def change_password(self, user: Any, new_password_hash: str) -> None:
        user.password_hash = new_password_hash
        self.session.add(user)
        self.session.commit()

    def list_api_keys(self, user_id: str):
        from sqlalchemy import select

        from infrastructure_atlas.db.models import UserAPIKey
        from infrastructure_atlas.infrastructure.db import mappers

        stmt = (
            select(UserAPIKey)
            .where(UserAPIKey.user_id == user_id)
            .order_by(UserAPIKey.provider.asc())
        )
        records = self.session.execute(stmt).scalars().all()
        return [mappers.user_api_key_to_entity(record) for record in records]

    def save_api_key(self, user: Any, provider: str, secret: str, label: str | None):
        from sqlalchemy import select

        from infrastructure_atlas.db.models import UserAPIKey
        from infrastructure_atlas.infrastructure.db import mappers

        stmt = select(UserAPIKey).where(
            UserAPIKey.user_id == user.id,
            UserAPIKey.provider == provider,
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None:
            record = UserAPIKey(user_id=user.id, provider=provider, secret=secret, label=label)
            self.session.add(record)
        else:
            record.secret = secret
            record.label = label
        self.session.commit()
        self.session.refresh(record)
        return mappers.user_api_key_to_entity(record)

    def delete_api_key(self, user: Any, provider: str) -> None:
        from sqlalchemy import select

        from infrastructure_atlas.db.models import UserAPIKey

        stmt = select(UserAPIKey).where(
            UserAPIKey.user_id == user.id,
            UserAPIKey.provider == provider,
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        if not record:
            raise LookupError("API key not found")
        self.session.delete(record)
        self.session.commit()


class MongoDBProfileService:
    """MongoDB-based profile service."""

    def __init__(self, user_repo: Any, api_key_repo: Any) -> None:
        self._user_repo = user_repo
        self._api_key_repo = api_key_repo

    def update_profile(self, user: Any, display_name: str | None, email: str | None):
        return self._user_repo.update(
            user.id,
            display_name=display_name,
            email=email,
        )

    def change_password(self, user: Any, new_password_hash: str) -> None:
        self._user_repo.update(user.id, password_hash=new_password_hash)

    def list_api_keys(self, user_id: str):
        return self._api_key_repo.list_for_user(user_id)

    def save_api_key(self, user: Any, provider: str, secret: str, label: str | None):
        return self._api_key_repo.upsert(
            user_id=user.id,
            provider=provider,
            secret=secret,
            label=label,
        )

    def delete_api_key(self, user: Any, provider: str) -> None:
        if not self._api_key_repo.delete(user.id, provider):
            raise LookupError("API key not found")


def create_profile_service(session: Any = None) -> ProfileServiceProtocol:
    """Create a profile service using the configured storage backend."""
    from infrastructure_atlas.infrastructure.repository_factory import get_storage_backend

    backend = get_storage_backend()

    if backend == "mongodb":
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client
        from infrastructure_atlas.infrastructure.mongodb.repositories import (
            MongoDBUserAPIKeyRepository,
            MongoDBUserRepository,
        )

        client = get_mongodb_client()
        user_repo = MongoDBUserRepository(client.atlas)
        api_key_repo = MongoDBUserAPIKeyRepository(client.atlas)
        return MongoDBProfileService(user_repo, api_key_repo)
    else:
        from infrastructure_atlas.application.services.users import create_user_service

        if session is None:
            from infrastructure_atlas.db import get_sessionmaker

            SessionLocal = get_sessionmaker()
            session = SessionLocal()
        return ProfileService(session=session, user_service=create_user_service(session))


__all__ = ["ProfileService", "MongoDBProfileService", "create_profile_service"]
