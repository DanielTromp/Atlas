"""DTOs for suggestion board endpoints."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .base import DomainModel


class SuggestionCommentDTO(DomainModel):
    id: str
    text: str
    created_at: datetime | str


class SuggestionDTO(DomainModel):
    id: str
    title: str
    summary: str
    classification: str
    status: str
    likes: int
    created_at: datetime | str
    updated_at: datetime | str
    classification_color: str | None = None
    classification_letter: str | None = None
    status_label: str | None = None
    comments: list[SuggestionCommentDTO] = []


class SuggestionMetaClassification(DomainModel):
    name: str
    color: str | None = None
    letter: str | None = None


class SuggestionMetaStatus(DomainModel):
    value: str
    label: str


class SuggestionMetaDTO(DomainModel):
    classifications: list[SuggestionMetaClassification]
    statuses: list[SuggestionMetaStatus]


class SuggestionListDTO(DomainModel):
    items: list[SuggestionDTO]
    total: int
    meta: SuggestionMetaDTO


class SuggestionItemDTO(DomainModel):
    item: SuggestionDTO
    meta: SuggestionMetaDTO | None = None


class SuggestionCommentResponseDTO(DomainModel):
    item: SuggestionDTO
    comment: SuggestionCommentDTO


def suggestion_to_dto(data: dict) -> SuggestionDTO:
    return SuggestionDTO.model_validate(data)


def suggestions_to_dto(items: Iterable[dict]) -> list[SuggestionDTO]:
    return [suggestion_to_dto(item) for item in items]


def meta_to_dto(meta: dict) -> SuggestionMetaDTO:
    return SuggestionMetaDTO.model_validate(meta)


__all__ = [
    "SuggestionCommentDTO",
    "SuggestionCommentResponseDTO",
    "SuggestionDTO",
    "SuggestionItemDTO",
    "SuggestionListDTO",
    "SuggestionMetaClassification",
    "SuggestionMetaDTO",
    "SuggestionMetaStatus",
    "meta_to_dto",
    "suggestion_to_dto",
    "suggestions_to_dto",
]
