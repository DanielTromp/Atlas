"""Profile management service orchestrating user operations."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from enreach_tools.application.services.users import DefaultUserService, create_user_service
from enreach_tools.db.models import User, UserAPIKey
from enreach_tools.infrastructure.db import mappers


@dataclass(slots=True)
class ProfileService:
    session: Session
    user_service: DefaultUserService

    def update_profile(self, user: User, display_name: str | None, email: str | None):
        user.display_name = display_name
        user.email = email
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return mappers.user_to_entity(user)

    def change_password(self, user: User, new_password_hash: str) -> None:
        user.password_hash = new_password_hash
        self.session.add(user)
        self.session.commit()

    def list_api_keys(self, user_id: str):
        stmt = (
            select(UserAPIKey)
            .where(UserAPIKey.user_id == user_id)
            .order_by(UserAPIKey.provider.asc())
        )
        records = self.session.execute(stmt).scalars().all()
        return [mappers.user_api_key_to_entity(record) for record in records]

    def save_api_key(self, user: User, provider: str, secret: str, label: str | None):
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

    def delete_api_key(self, user: User, provider: str) -> None:
        stmt = select(UserAPIKey).where(
            UserAPIKey.user_id == user.id,
            UserAPIKey.provider == provider,
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        if not record:
            raise LookupError("API key not found")
        self.session.delete(record)
        self.session.commit()


def create_profile_service(session: Session) -> ProfileService:
    return ProfileService(session=session, user_service=create_user_service(session))


__all__ = ["ProfileService", "create_profile_service"]
