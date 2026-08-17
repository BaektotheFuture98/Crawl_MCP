from __future__ import annotations

import builtins
from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from crawling_mcp.domain.articles import (
    Article,
    ArticleCandidate,
    ArticleChangeSummary,
    ArticleCrawlState,
    ArticleCrawlStateCreate,
)
from crawling_mcp.domain.models import CrawlExecution, CrawlRequest, CrawlResult
from crawling_mcp.domain.monitoring import (
    CrawlRun,
    CrawlRunCreate,
    CrawlTarget,
    CrawlTargetCreate,
    MonitoringRunResult,
)


class CrawlRunner(Protocol):
    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult: ...


class TargetRunner(Protocol):
    async def run_target(
        self, target_id: UUID, *, force: bool = False
    ) -> MonitoringRunResult | None: ...


class TargetRepository(Protocol):
    async def create(self, target: CrawlTargetCreate) -> CrawlTarget: ...

    async def get(self, target_id: UUID) -> CrawlTarget | None: ...

    async def list(
        self, *, enabled: bool | None = None, limit: int = 100
    ) -> builtins.list[CrawlTarget]: ...

    async def save(self, target: CrawlTarget) -> CrawlTarget: ...

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_owner: str,
        lease_seconds: int,
    ) -> builtins.list[CrawlTarget]: ...

    async def claim(
        self,
        target_id: UUID,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        force: bool,
    ) -> CrawlTarget | None: ...

    async def renew_lease(
        self,
        target_id: UUID,
        *,
        lease_owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool: ...

    async def mark_succeeded(
        self,
        target_id: UUID,
        *,
        lease_owner: str,
        crawled_at: datetime,
        next_crawl_at: datetime,
    ) -> bool: ...

    async def mark_failed(
        self,
        target_id: UUID,
        *,
        lease_owner: str,
        failed_at: datetime,
        error: str,
        next_retry_at: datetime,
    ) -> bool: ...


class ArticleRepository(Protocol):
    async def find_by_url(self, url: str) -> Article | None: ...

    async def get_by_id(self, article_id: UUID) -> Article | None: ...

    async def insert_or_get(self, candidate: ArticleCandidate) -> Article: ...

    async def update(self, article_id: UUID, candidate: ArticleCandidate) -> Article: ...


class ArticleCrawlStateRepository(Protocol):
    async def find_by_url(self, target_id: UUID, url: str) -> ArticleCrawlState | None: ...

    async def list_by_target(self, target_id: UUID) -> builtins.list[ArticleCrawlState]: ...

    async def create(self, state: ArticleCrawlStateCreate) -> ArticleCrawlState: ...

    async def save(self, state: ArticleCrawlState) -> ArticleCrawlState: ...

    async def recent_changes(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> builtins.list[ArticleChangeSummary]: ...


class CrawlRunRepository(Protocol):
    async def create(self, run: CrawlRunCreate) -> CrawlRun: ...

    async def save(self, run: CrawlRun) -> CrawlRun: ...

    async def save_terminal(self, run: CrawlRun) -> bool: ...

    async def fail_running(
        self, target_id: UUID, *, completed_at: datetime, error: str
    ) -> int: ...

    async def latest(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> builtins.list[CrawlRun]: ...


class MonitoringUnitOfWork(Protocol):
    targets: TargetRepository
    articles: ArticleRepository
    states: ArticleCrawlStateRepository
    runs: CrawlRunRepository

    async def __aenter__(self) -> MonitoringUnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    async def commit(self) -> None: ...


class MonitoringUnitOfWorkFactory(Protocol):
    def __call__(self) -> MonitoringUnitOfWork: ...
