"""DTO helpers for Foreman configuration."""

from __future__ import annotations

from datetime import datetime

from infrastructure_atlas.application.dto.base import DomainModel
from infrastructure_atlas.domain.entities import ForemanConfigEntity


class ForemanConfigDTO(DomainModel):
    id: str
    name: str
    base_url: str
    username: str
    verify_ssl: bool
    has_credentials: bool
    created_at: datetime
    updated_at: datetime


def foreman_config_to_dto(
    entity: ForemanConfigEntity,
    *,
    has_credentials: bool | None = None,
) -> ForemanConfigDTO:
    return ForemanConfigDTO(
        id=entity.id,
        name=entity.name,
        base_url=entity.base_url,
        username=entity.username,
        verify_ssl=entity.verify_ssl,
        has_credentials=bool(has_credentials if has_credentials is not None else entity.token_secret),
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def foreman_configs_to_dto(entities: list[ForemanConfigEntity]) -> list[ForemanConfigDTO]:
    return [foreman_config_to_dto(entity) for entity in entities]


__all__ = [
    "ForemanConfigDTO",
    "foreman_config_to_dto",
    "foreman_configs_to_dto",
]


