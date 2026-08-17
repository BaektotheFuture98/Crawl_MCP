from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crawling_mcp.domain.enums import CrawlJobStatus, CrawlMode
from crawling_mcp.domain.models import CrawlRequest, utc_now


class CrawlTarget(BaseModel):
    """Persisted bounded crawl schedule and operational state."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    url: str = Field(min_length=1, max_length=4096)
    interval_seconds: int = Field(ge=10, le=31_536_000)
    enabled: bool = True
    crawl_mode: CrawlMode = CrawlMode.AUTO
    auth_profile: str | None = Field(default=None, min_length=1, max_length=128)
    max_pages: int = Field(default=20, ge=1, le=500)
    max_depth: int = Field(default=2, ge=0, le=10)
    include_patterns: list[str] = Field(default_factory=list, max_length=100)
    exclude_patterns: list[str] = Field(default_factory=list, max_length=100)
    same_domain_only: bool = True
    max_request_retries: int = Field(default=2, ge=0, le=5)
    request_timeout_seconds: int = Field(default=30, ge=1, le=120)
    job_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    max_concurrency: int = Field(default=3, ge=1, le=20)
    respect_robots_txt: bool = True
    request_delay_seconds: float = Field(default=0.5, ge=0, le=60)
    remove_tracking_parameters: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_crawled_at: datetime | None = None
    next_crawl_at: datetime | None = None
    failure_count: int = Field(default=0, ge=0)
    last_error: str | None = None
    last_failed_at: datetime | None = None
    next_retry_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    discovery_watermark_at: datetime | None = None
    discovery_lag_seconds: int = Field(default=30, ge=0, le=86_400)
    discovery_overlap_seconds: int = Field(default=300, ge=0, le=604_800)

    def is_due(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        if self.lease_expires_at is not None and self.lease_expires_at > now:
            return False
        due_at = self.next_retry_at or self.next_crawl_at
        return due_at is None or due_at <= now

    def to_crawl_request(self) -> CrawlRequest:
        return CrawlRequest(
            start_url=self.url,
            crawl_mode=self.crawl_mode,
            auth_profile=self.auth_profile,
            max_pages=self.max_pages,
            max_depth=self.max_depth,
            include_patterns=list(self.include_patterns),
            exclude_patterns=list(self.exclude_patterns),
            same_domain_only=self.same_domain_only,
            max_request_retries=self.max_request_retries,
            request_timeout_seconds=self.request_timeout_seconds,
            job_timeout_seconds=self.job_timeout_seconds,
            max_concurrency=self.max_concurrency,
            respect_robots_txt=self.respect_robots_txt,
            request_delay_seconds=self.request_delay_seconds,
            remove_tracking_parameters=self.remove_tracking_parameters,
        )

    def retry_delay_seconds(self, *, base_seconds: int, max_seconds: int) -> int:
        return min(base_seconds * (1 << max(self.failure_count - 1, 0)), max_seconds)


class CrawlTargetCreate(BaseModel):
    """Client-owned target fields; PostgreSQL owns the UUIDv7 ID."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=4096)
    interval_seconds: int = Field(ge=10, le=31_536_000)
    enabled: bool = True
    crawl_mode: CrawlMode = CrawlMode.AUTO
    auth_profile: str | None = Field(default=None, min_length=1, max_length=128)
    max_pages: int = Field(default=20, ge=1, le=500)
    max_depth: int = Field(default=2, ge=0, le=10)
    include_patterns: list[str] = Field(default_factory=list, max_length=100)
    exclude_patterns: list[str] = Field(default_factory=list, max_length=100)
    same_domain_only: bool = True
    max_request_retries: int = Field(default=2, ge=0, le=5)
    request_timeout_seconds: int = Field(default=30, ge=1, le=120)
    job_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    max_concurrency: int = Field(default=3, ge=1, le=20)
    respect_robots_txt: bool = True
    request_delay_seconds: float = Field(default=0.5, ge=0, le=60)
    remove_tracking_parameters: bool = True
    discovery_lag_seconds: int = Field(default=30, ge=0, le=86_400)
    discovery_overlap_seconds: int = Field(default=300, ge=0, le=604_800)


class ConfigureTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: UUID | None = None
    url: str | None = Field(default=None, min_length=1, max_length=4096)
    interval_seconds: int | None = Field(default=None, ge=10, le=31_536_000)
    enabled: bool | None = None
    crawl_mode: CrawlMode | None = None
    auth_profile: str | None = Field(default=None, min_length=1, max_length=128)
    max_pages: int | None = Field(default=None, ge=1, le=500)
    max_depth: int | None = Field(default=None, ge=0, le=10)
    discovery_lag_seconds: int | None = Field(default=None, ge=0, le=86_400)
    discovery_overlap_seconds: int | None = Field(default=None, ge=0, le=604_800)


class CrawlRun(BaseModel):
    """Compact metadata for one Worker target execution."""

    id: UUID
    target_id: UUID
    status: CrawlJobStatus
    visited_pages: int = 0
    discovered_articles: int = 0
    inserted_articles: int = 0
    duplicate_articles: int = 0
    failed_pages: int = 0
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    error: str | None = None


class CrawlRunCreate(BaseModel):
    """Run fields before PostgreSQL supplies its UUIDv7 ID."""

    target_id: UUID
    status: CrawlJobStatus = CrawlJobStatus.RUNNING
    started_at: datetime = Field(default_factory=utc_now)


class CollectionResult(BaseModel):
    target_id: UUID
    crawl_run_id: UUID
    visited_pages: int = 0
    discovered_articles: int = 0
    inserted_articles: int = 0
    duplicate_articles: int = 0
    failed_pages: int = 0

    @model_validator(mode="after")
    def validate_counts(self) -> CollectionResult:
        if self.discovered_articles != self.inserted_articles + self.duplicate_articles:
            raise ValueError("discovered articles must equal inserted plus duplicate articles")
        return self
