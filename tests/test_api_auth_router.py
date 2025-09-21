"""Contract tests for the auth router."""
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from enreach_tools.db.models import User
from enreach_tools.domain.entities import UserEntity
from enreach_tools.interfaces.api.dependencies import current_user, get_user_service
from enreach_tools.interfaces.api.routes.auth import router


class _StubUserService:
    def __init__(self, entity: UserEntity):
        self._entity = entity

    def get_current_user(self, user_id: str) -> UserEntity | None:  # pragma: no cover - exercised via API call
        if user_id == self._entity.id:
            return self._entity
        return None

    # Additional interface methods (unused in this test)
    def get_user_by_username(self, username: str):  # pragma: no cover
        return None

    def list_users(self):  # pragma: no cover
        return []

    def list_api_keys(self, user_id: str):  # pragma: no cover
        return []

    def get_global_api_key(self, provider: str):  # pragma: no cover
        return None


def test_auth_me_returns_current_user_payload():
    now = datetime.now(UTC)
    entity = UserEntity(
        id="user-1",
        username="alice",
        display_name="Alice",
        email="alice@example.com",
        role="admin",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    orm_user = User(
        id="user-1",
        username="alice",
        display_name="Alice",
        email="alice@example.com",
        role="admin",
        password_hash=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user_service] = lambda: _StubUserService(entity)
    app.dependency_overrides[current_user] = lambda: orm_user

    with TestClient(app) as client:
        response = client.get("/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "alice"
    assert payload["role"] == "admin"
    assert payload["is_active"] is True
