"""Contract tests for the profile router."""
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from infrastructure_atlas.application.security import hash_password
from infrastructure_atlas.db.models import User
from infrastructure_atlas.domain.entities import UserAPIKeyEntity, UserEntity
from infrastructure_atlas.interfaces.api.dependencies import current_user, get_profile_service
from infrastructure_atlas.interfaces.api.routes import profile


class _StubProfileService:
    def __init__(self, entity: UserEntity):
        self.entity = entity
        self.updated = None
        self.changed_password_hash = None
        self.keys = [
            UserAPIKeyEntity(
                id="key-1",
                user_id=entity.id,
                provider="netbox",
                label="NetBox",
                secret="secret",
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )
        ]

    def update_profile(self, user, display_name, email):
        self.updated = (display_name, email)
        return UserEntity(
            id=self.entity.id,
            username=self.entity.username,
            display_name=display_name,
            email=email,
            role=self.entity.role,
             permissions=self.entity.permissions,
            is_active=self.entity.is_active,
            created_at=self.entity.created_at,
            updated_at=self.entity.updated_at,
        )

    def change_password(self, user, new_hash):
        self.changed_password_hash = new_hash

    def list_api_keys(self, user_id: str):
        return list(self.keys)

    def save_api_key(self, user, provider: str, secret: str, label: str | None):
        entity = UserAPIKeyEntity(
            id="key-2",
            user_id=user.id,
            provider=provider,
            label=label,
            secret=secret,
            created_at=self.entity.created_at,
            updated_at=self.entity.updated_at,
        )
        self.keys.append(entity)
        return entity

    def delete_api_key(self, user, provider: str):
        before = len(self.keys)
        self.keys = [k for k in self.keys if k.provider != provider]
        if len(self.keys) == before:
            raise LookupError("missing")


def _build_app(service: _StubProfileService, orm_user: User) -> TestClient:
    app = FastAPI()
    app.include_router(profile.router)
    app.dependency_overrides[get_profile_service] = lambda: service
    app.dependency_overrides[current_user] = lambda: orm_user
    return TestClient(app)


def _user_entity() -> UserEntity:
    now = datetime.now(UTC)
    return UserEntity(
        id="user-1",
        username="alice",
        display_name="Alice",
        email="alice@example.com",
        role="admin",
        permissions=frozenset({"chat.use", "tools.use"}),
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _orm_user(entity: UserEntity) -> User:
    return User(
        id=entity.id,
        username=entity.username,
        display_name=entity.display_name,
        email=entity.email,
        role=entity.role,
        password_hash=hash_password("old-password"),
        is_active=entity.is_active,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def test_update_profile_returns_dto():
    entity = _user_entity()
    orm_user = _orm_user(entity)
    service = _StubProfileService(entity)

    with _build_app(service, orm_user) as client:
        resp = client.patch("/profile", json={"display_name": "New Name", "email": "new@example.com"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["display_name"] == "New Name"
    assert payload["email"] == "new@example.com"
    assert service.updated == ("New Name", "new@example.com")


def test_change_password_validates_hash():
    entity = _user_entity()
    orm_user = _orm_user(entity)
    service = _StubProfileService(entity)

    with _build_app(service, orm_user) as client:
        resp = client.post(
            "/profile/password",
            json={"current_password": "old-password", "new_password": "long-new-pass"},
        )

    assert resp.status_code == 200
    assert service.changed_password_hash is not None


def test_list_and_manage_api_keys():
    entity = _user_entity()
    orm_user = _orm_user(entity)
    service = _StubProfileService(entity)

    with _build_app(service, orm_user) as client:
        list_resp = client.get("/profile/api-keys")
        assert list_resp.status_code == 200
        assert list_resp.json()[0]["provider"] == "netbox"

        upsert_resp = client.put(
            "/profile/api-keys/openai",
            json={"secret": "secret-token", "label": "OpenAI"},
        )
        assert upsert_resp.status_code == 200
        assert upsert_resp.json()["provider"] == "openai"

        delete_resp = client.delete("/profile/api-keys/netbox")
        assert delete_resp.status_code == 200

    # deleting missing provider returns 404
    with _build_app(service, orm_user) as client:
        resp = client.delete("/profile/api-keys/missing")
    assert resp.status_code == 404
