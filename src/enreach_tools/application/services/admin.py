"""Administrative user management services."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from enreach_tools.application.security import hash_password
from enreach_tools.db.models import GlobalAPIKey, RolePermission, User
from enreach_tools.infrastructure.db import mappers


@dataclass(slots=True)
class AdminService:
    session: Session

    def _normalize_role(self, role: str) -> str:
        return (role or "").strip().lower()

    def ensure_role_defined(self, role: str) -> str:
        normalized = self._normalize_role(role)
        if not normalized:
            raise ValueError("Role is required")
        record = self.session.get(RolePermission, normalized)
        if record is None:
            raise ValueError(f"Role '{normalized}' is not defined")
        return normalized

    def _role_permissions(self, role: str) -> frozenset[str]:
        record = self.session.get(RolePermission, role)
        values = record.permissions if record else []
        return frozenset(values or [])

    def _attach_user_permissions(self, entity):
        if entity is None:
            return None
        entity.permissions = self._role_permissions(entity.role)
        return entity

    def list_users(self, include_inactive: bool = False):
        stmt = select(User)
        if not include_inactive:
            stmt = stmt.where(User.is_active.is_(True))
        stmt = stmt.order_by(User.username.asc())
        records = self.session.execute(stmt).scalars().all()
        cache: dict[str, frozenset[str]] = {}
        entities = []
        for record in records:
            entity = mappers.user_to_entity(record)
            perms = cache.get(entity.role)
            if perms is None:
                perms = self._role_permissions(entity.role)
                cache[entity.role] = perms
            entity.permissions = perms
            entities.append(entity)
        return entities

    def create_user(self, username: str, password: str, display_name: str | None, email: str | None, role: str):
        role_norm = self.ensure_role_defined(role)
        user = User(
            username=username,
            display_name=display_name,
            email=email,
            role=role_norm,
            is_active=True,
            password_hash=hash_password(password),
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        entity = mappers.user_to_entity(user)
        return self._attach_user_permissions(entity)

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
        if user.role:
            user.role = self.ensure_role_defined(user.role)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        entity = mappers.user_to_entity(user)
        return self._attach_user_permissions(entity)

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

    def list_role_permissions(self):
        stmt = select(RolePermission).order_by(RolePermission.role.asc())
        records = self.session.execute(stmt).scalars().all()
        return [mappers.role_permission_to_entity(record) for record in records]

    def get_role_permission(self, role: str):
        normalized = self._normalize_role(role)
        record = self.session.get(RolePermission, normalized)
        return mappers.role_permission_to_entity(record) if record else None

    def update_role_permission(self, role: str, label: str | None, description: str | None, permissions: list[str]):
        normalized = self._normalize_role(role)
        record = self.session.get(RolePermission, normalized)
        if record is None:
            raise ValueError("Role not found")
        label_value = (label or record.label or normalized).strip() or normalized
        description_value = (
            description.strip()
            if isinstance(description, str) and description.strip()
            else None
        )
        cleaned_set: set[str] = set()
        for perm in permissions:
            if perm is None:
                continue
            text = str(perm).strip()
            if not text:
                continue
            cleaned_set.add(text)
        record.label = label_value
        record.description = description_value
        record.permissions = sorted(cleaned_set)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return mappers.role_permission_to_entity(record)

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
