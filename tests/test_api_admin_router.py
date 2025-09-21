"""Contract tests for admin router operations."""
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from enreach_tools.application.security import hash_password
from enreach_tools.domain.entities import GlobalAPIKeyEntity, UserEntity
from enreach_tools.interfaces.api.dependencies import current_user, get_admin_service
from enreach_tools.interfaces.api.routes import admin as admin_routes


class _StubAdminService:
    def __init__(self):
        self.users: list[UserEntity] = []
        self.keys: list[GlobalAPIKeyEntity] = []
        now = datetime.now(UTC)
        self.admin_entity = UserEntity(
            id="admin-1",
            username="admin",
            display_name="Admin",
            email="admin@example.com",
            role="admin",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.users.append(self.admin_entity)
        self._orm_users: dict[str, _OrmUser] = {}
        self._store_orm(self.admin_entity)

    # Users
    def list_users(self, include_inactive: bool = False):
        if include_inactive:
            return self.users
        return [u for u in self.users if u.is_active]

    def ensure_username_available(self, username: str) -> None:
        if any(u.username == username for u in self.users):
            raise ValueError("Username already exists")

    def create_user(self, username: str, password: str, display_name: str | None, email: str | None, role: str):
        now = datetime.now(UTC)
        entity = UserEntity(
            id=f"user-{len(self.users)+1}",
            username=username,
            display_name=display_name,
            email=email,
            role=role,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.users.append(entity)
        self._store_orm(entity)
        return entity

    def get_user(self, user_id: str):
        return self._orm_users.get(user_id)

    def get_user_by_username(self, username: str):
        for entity in self.users:
            if entity.username == username:
                return self._orm_users[entity.id]
        return None

    def save_user(self, orm_user):
        for idx, user in enumerate(self.users):
            if user.id == orm_user.id:
                self.users[idx] = UserEntity(
                    id=orm_user.id,
                    username=orm_user.username,
                    display_name=orm_user.display_name,
                    email=orm_user.email,
                    role=orm_user.role,
                    is_active=orm_user.is_active,
                    created_at=user.created_at,
                    updated_at=datetime.now(UTC),
                )
                self._store_orm(self.users[idx])
                return self.users[idx]
        raise ValueError("User not found")

    def delete_user(self, orm_user):
        self.users = [u for u in self.users if u.id != orm_user.id]
        self._orm_users.pop(orm_user.id, None)

    def set_password(self, orm_user, password: str):
        orm_user.password_hash = hash_password(password)

    # Global API keys
    def list_global_api_keys(self):
        return self.keys

    def upsert_global_api_key(self, provider: str, secret: str, label: str | None):
        now = datetime.now(UTC)
        entity = GlobalAPIKeyEntity(
            id=f"key-{provider}",
            provider=provider,
            label=label,
            secret=secret,
            created_at=now,
            updated_at=now,
        )
        self.keys = [k for k in self.keys if k.provider != provider]
        self.keys.append(entity)
        return entity

    def delete_global_api_key(self, provider: str) -> bool:
        before = len(self.keys)
        self.keys = [k for k in self.keys if k.provider != provider]
        return len(self.keys) != before

    def _store_orm(self, entity: UserEntity):
        self._orm_users[entity.id] = _OrmUser(entity)


class _OrmUser:
    def __init__(self, entity: UserEntity):
        self.id = entity.id
        self.username = entity.username
        self.display_name = entity.display_name
        self.email = entity.email
        self.role = entity.role
        self.is_active = entity.is_active
        self.password_hash = hash_password("placeholder")
        self.created_at = entity.created_at
        self.updated_at = entity.updated_at


def _build_client(service: _StubAdminService) -> TestClient:
    app = FastAPI()
    app.include_router(admin_routes.router)
    app.dependency_overrides[get_admin_service] = lambda: service
    app.dependency_overrides[current_user] = lambda: type(
        "OrmAdmin",
        (),
        {
            "id": service.admin_entity.id,
            "username": service.admin_entity.username,
            "display_name": service.admin_entity.display_name,
            "email": service.admin_entity.email,
            "role": service.admin_entity.role,
            "is_active": True,
            "password_hash": hash_password("admin-pass"),
        },
    )()
    return TestClient(app)


def test_list_and_create_users():
    service = _StubAdminService()
    with _build_client(service) as client:
        resp = client.get("/admin/users")
        assert resp.status_code == 200
        assert resp.json()[0]["username"] == "admin"

        resp = client.post(
            "/admin/users",
            json={
                "username": "alice",
                "password": "securepass",
                "display_name": "Alice",
                "email": "alice@example.com",
                "role": "member",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "alice"


def test_update_and_delete_user():
    service = _StubAdminService()
    new_entity = service.create_user("bob", "securepass", "Bob", "bob@example.com", "member")

    with _build_client(service) as client:
        resp = client.patch(
            f"/admin/users/{new_entity.id}",
            json={"display_name": "Bobbie", "is_active": True},
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Bobbie"

        resp = client.post(
            f"/admin/users/{new_entity.id}/password",
            json={"new_password": "anotherpass"},
        )
        assert resp.status_code == 200

        resp = client.delete(f"/admin/users/{new_entity.id}")
        assert resp.status_code == 200


def test_manage_global_api_keys():
    service = _StubAdminService()
    with _build_client(service) as client:
        resp = client.put(
            "/admin/global-api-keys/netbox",
            json={"secret": "secret", "label": "NetBox"},
        )
        assert resp.status_code == 200
        assert resp.json()["provider"] == "netbox"

        resp = client.get("/admin/global-api-keys")
        assert resp.status_code == 200
        assert resp.json()[0]["provider"] == "netbox"

        resp = client.delete("/admin/global-api-keys/netbox")
        assert resp.status_code == 200
