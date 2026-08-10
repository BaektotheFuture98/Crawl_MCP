from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from crawling_mcp.domain.enums import ChangeType
from crawling_mcp.domain.models import utc_now


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


class ArticleCrawlState(BaseModel):
    """Crawler-owned latest observation state without an article body."""

    article_id: UUID
    target_id: UUID
    url: str
    content_hash: str = Field(min_length=64, max_length=64)
    etag: str | None = None
    last_modified: str | None = None
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    last_changed_at: datetime | None = None
    last_change_type: ChangeType | None = None


class ArticleCrawlStateCreate(BaseModel):
    """Initial crawl state for a DB-owned article identity."""

    model_config = ConfigDict(extra="forbid")

    article_id: UUID
    target_id: UUID
    url: str
    content_hash: str = Field(min_length=64, max_length=64)
    etag: str | None = None
    last_modified: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    last_changed_at: datetime | None = None
    last_change_type: ChangeType | None = None


class ArticleObservation(BaseModel):
    """A candidate plus HTTP validators observed during one crawl."""

    candidate: ArticleCandidate
    etag: str | None = None
    last_modified: str | None = None


class ArticlePersistenceResult(BaseModel):
    """Compact result of one article persistence decision."""

    article_id: UUID
    url: str
    change_type: ChangeType


class ArticleChangeSummary(BaseModel):
    """Bounded Hermes-facing change record that intentionally excludes content."""

    article_id: UUID
    target_id: UUID
    change_type: ChangeType
    title: str = ""
    publisher: str | None = None
    url: str
    published_at: datetime | None = None
    last_changed_at: datetime


class ArticleExtractionMetadata(BaseModel):
    """Optional adapter diagnostics kept outside final article persistence."""

    extractor: str
    values: dict[str, Any] = Field(default_factory=dict)
