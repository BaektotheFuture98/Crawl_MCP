from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ArticleCandidate(BaseModel):
    """Site-aware article data before persistence assigns an identity."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=4096)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    reporter: str | None = Field(default=None, max_length=100)
    publisher: str | None = Field(default=None, max_length=100)
    published_at: datetime | None = None


class Article(BaseModel):
    """The existing final ARTICLE table contract."""

    id: UUID
    url: str
    title: str = ""
    content: str = ""
    reporter: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None

    def as_candidate(self) -> ArticleCandidate:
        return ArticleCandidate(
            url=self.url,
            title=self.title,
            content=self.content,
            reporter=self.reporter,
            publisher=self.publisher,
            published_at=self.published_at,
        )


class ArticleInsertResult(BaseModel):
    """Result of a conflict-safe insert into the globally unique ARTICLE table."""

    model_config = ConfigDict(frozen=True)

    article: Article
    inserted: bool


class ArticleExtractionMetadata(BaseModel):
    """Optional adapter diagnostics kept outside final article persistence."""

    extractor: str
    values: dict[str, Any] = Field(default_factory=dict)
