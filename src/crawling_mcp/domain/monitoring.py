from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus, CrawlMode
from crawling_mcp.domain.models import CrawlRequest, utc_now


class CrawlTarget(BaseModel):
    """A persisted bounded crawl schedule and its operational state."""

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

    def is_due(self, now: datetime) -> bool:
        """Return whether a worker may claim this target at `now`."""
        if not self.enabled:
            return False
        if self.lease_expires_at is not None and self.lease_expires_at > now:
            return False
        due_at = self.next_retry_at or self.next_crawl_at
        return due_at is None or due_at <= now

    def to_crawl_request(self) -> CrawlRequest:
        """Convert persisted target configuration into the existing use-case request."""
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
        """Return capped exponential delay for the current failure count."""
        exponent = max(self.failure_count - 1, 0)
        return min(base_seconds * (1 << exponent), max_seconds)


class CrawlTargetCreate(BaseModel):
    """Client-owned fields used to create a target; ID is database-owned."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=4096)
    interval_seconds: int = Field(ge=10, le=31_536_000)
    enabled: bool = True
    crawl_mode: CrawlMode = CrawlMode.AUTO
    auth_profile: str | None = Field(default=None, min_length=1, max_length=128)
    max_pages: int = Field(default=20, ge=1, le=500)
    max_depth: int = Field(default=2, ge=0, le=10)


class CrawlSnapshot(BaseModel):
    """One changed canonical page version and its HTTP validators."""

    id: UUID
    target_id: UUID
    article_id: UUID | None = None
    url: str
    content_hash: str = Field(min_length=64, max_length=64)
    title: str = ""
    content: str | None = None
    source: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    depth: int = Field(default=0, ge=0)
    collected_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)


class CrawlSnapshotCreate(BaseModel):
    """Changed page version before persistence assigns its identifiers."""

    model_config = ConfigDict(extra="forbid")

    target_id: UUID
    url: str
    content_hash: str = Field(min_length=64, max_length=64)
    title: str = ""
    content: str
    source: str | None = None
    published_at: datetime | None = None
    reporter: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    depth: int = Field(default=0, ge=0)
    collected_at: datetime = Field(default_factory=utc_now)


class CrawlChange(BaseModel):
    """A compact persisted NEW or UPDATED event."""

    id: UUID
    target_id: UUID
    change_type: ChangeType
    url: str
    title: str = ""
    previous_snapshot_id: UUID | None = None
    current_snapshot_id: UUID
    detected_at: datetime = Field(default_factory=utc_now)


class CrawlChangeCreate(BaseModel):
    """Change event before persistence assigns its identifier."""

    model_config = ConfigDict(extra="forbid")

    target_id: UUID
    change_type: ChangeType
    url: str
    title: str = ""
    previous_snapshot_id: UUID | None = None
    current_snapshot_id: UUID
    detected_at: datetime = Field(default_factory=utc_now)


class CrawlJobSummary(BaseModel):
    """Small monitoring job status returned to MCP clients."""

    job_id: UUID
    target_id: UUID
    status: CrawlJobStatus
    checked: int = 0
    changed: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    error: str | None = None


class MonitoringRunResult(BaseModel):
    """Internal result of one target run."""

    target_id: UUID
    job_id: UUID
    checked: int = 0
    changed: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
