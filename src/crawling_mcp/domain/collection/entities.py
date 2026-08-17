from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class CollectionWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_order(self) -> CollectionWindow:
        if as_utc(self.start) > as_utc(self.end):
            raise ValueError("collection window start must not be after end")
        return self

    def contains(self, published_at: datetime | None) -> bool:
        if published_at is None:
            return False
        value = as_utc(published_at)
        return as_utc(self.start) <= value < as_utc(self.end)


class ArticleDiscovery(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_id: UUID
    article_id: UUID
    discovered_at: datetime


class ArticleDiscoveryCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_id: UUID
    article_id: UUID
    discovered_at: datetime
