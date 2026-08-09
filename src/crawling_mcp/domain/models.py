from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from crawling_mcp.domain.enums import CrawlMode, ErrorCode, PageType


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(UTC)


class ScrapePageRequest(BaseModel):
    """Validated single-page crawl request."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=4096)
    crawl_mode: CrawlMode = CrawlMode.AUTO
    auth_profile: str | None = Field(default=None, min_length=1, max_length=128)
    request_timeout_seconds: int = Field(default=30, ge=1, le=120)


class CrawlRequest(BaseModel):
    """Validated bounded site crawl request."""

    model_config = ConfigDict(extra="forbid")

    start_url: str = Field(min_length=1, max_length=4096)
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


class CrawlLimits(BaseModel):
    """Operator-controlled ceilings applied before any network activity."""

    max_pages: int = Field(default=500, ge=1, le=500)
    max_depth: int = Field(default=10, ge=0, le=10)
    max_request_retries: int = Field(default=5, ge=0, le=5)
    request_timeout_seconds: int = Field(default=120, ge=1, le=120)
    job_timeout_seconds: int = Field(default=3600, ge=1, le=3600)
    max_concurrency: int = Field(default=20, ge=1, le=20)


class PageSnapshot(BaseModel):
    """Engine-neutral representation of a fetched page."""

    url: str
    html: str
    status_code: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    page_type: PageType = PageType.DETAIL
    links: list[str] = Field(default_factory=list)
    depth: int = 0


class PageItem(BaseModel):
    """Structured page data returned to clients."""

    url: str
    title: str = ""
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    meta_description: str | None = None
    canonical_url: str | None = None
    language: str | None = None
    http_status_code: int | None = None
    published_at: datetime | None = None
    source: str | None = None
    raw_html: str | None = Field(default=None, exclude=True, repr=False)
    collected_at: datetime = Field(default_factory=utc_now)


class CrawlFailure(BaseModel):
    """Safe per-page crawl failure."""

    url: str
    error_code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)


class CrawlResult(BaseModel):
    """Aggregate site crawl result."""

    job_id: UUID = Field(default_factory=uuid4)
    start_url: str
    visited_pages: int = 0
    succeeded_pages: int = 0
    failed_pages: int = 0
    items: list[PageItem] = Field(default_factory=list)
    failures: list[CrawlFailure] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class ErrorResponse(BaseModel):
    """Client-safe error payload."""

    error_code: ErrorCode
    message: str
    job_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidatedUrl(BaseModel):
    """URL and DNS answers approved by the SSRF policy."""

    url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


class CrawlContext(BaseModel):
    """Per-job state passed to crawler ports."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    job_id: UUID = Field(default_factory=uuid4)
    domain: str
    adapter_name: str = "generic"
    authenticated: bool = False
    browser_context: Any | None = None


class AuthProfile(BaseModel):
    """Non-secret authentication profile configuration."""

    domain: str
    adapter: str
    username_env: str
    password_env: str
    storage_state_path: str


class Credentials(BaseModel):
    """Credentials resolved from a secret provider."""

    username: str
    password: str


class SupportedSite(BaseModel):
    """Public registry metadata."""

    domain: str
    authentication: str
    extractor: str


class ArtifactPaths(BaseModel):
    """Paths to failure diagnostics captured for a job."""

    error_json: str
    html: str | None = None
    screenshot: str | None = None
    accessibility_snapshot: str | None = None
