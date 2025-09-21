"""Administrative user management services."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from enreach_tools.application.security import hash_password
from enreach_tools.db.models import GlobalAPIKey, User
from enreach_tools.infrastructure.db import mappers


@dataclass(slots=True)
class AdminService:
    session: Session

    def list_users(self, include_inactive: bool = False):
        stmt = select(User)
        if not include_inactive:
            stmt = stmt.where(User.is_active.is_(True))
        stmt = stmt.order_by(User.username.asc())
        records = self.session.execute(stmt).scalars().all()
        return [mappers.user_to_entity(record) for record in records]

    def create_user(self, username: str, password: str, display_name: str | None, email: str | None, role: str):
        user = User(
            username=username,
            display_name=display_name,
            email=email,
            role=role,
            is_active=True,
            password_hash=hash_password(password),
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return mappers.user_to_entity(user)

    def get_user(self, user_id: str) -> User | None:
        return self.session.get(User, user_id)

    def get_user_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return self.session.execute(stmt).scalar_one_or_none()

    def ensure_username_available(self, username: str) -> None:
        stmt = select(User).where(User.username == username)
        if self.session.execute(stmt).scalar_one_or_none():
            raise ValueError("Username already exists")

    def save_user(self, user: User):
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return mappers.user_to_entity(user)

    def set_password(self, user: User, password: str):
        user.password_hash = hash_password(password)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return mappers.user_to_entity(user)

    def delete_user(self, user: User):
        self.session.delete(user)
        self.session.commit()

    def list_global_api_keys(self):
        stmt = select(GlobalAPIKey).order_by(GlobalAPIKey.provider.asc())
        records = self.session.execute(stmt).scalars().all()
        return [mappers.global_api_key_to_entity(record) for record in records]

    def upsert_global_api_key(self, provider: str, secret: str, label: str | None):
        stmt = select(GlobalAPIKey).where(GlobalAPIKey.provider == provider)
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None:
            record = GlobalAPIKey(provider=provider, secret=secret, label=label)
            self.session.add(record)
        else:
            record.secret = secret
            record.label = label
        self.session.commit()
        self.session.refresh(record)
        return mappers.global_api_key_to_entity(record)

    def delete_global_api_key(self, provider: str) -> bool:
        stmt = select(GlobalAPIKey).where(GlobalAPIKey.provider == provider)
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None:
            return False
        self.session.delete(record)
        self.session.commit()
        return True


def create_admin_service(session: Session) -> AdminService:
    return AdminService(session=session)


__all__ = ["AdminService", "create_admin_service"]
