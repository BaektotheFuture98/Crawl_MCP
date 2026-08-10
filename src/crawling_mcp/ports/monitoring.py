from __future__ import annotations

import builtins
from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from crawling_mcp.domain.models import CrawlExecution, CrawlRequest, CrawlResult
from crawling_mcp.domain.monitoring import (
    CrawlChange,
    CrawlChangeCreate,
    CrawlJobSummary,
    CrawlSnapshot,
    CrawlSnapshotCreate,
    CrawlTarget,
    CrawlTargetCreate,
    MonitoringRunResult,
)


class CrawlRunner(Protocol):
    """Application-facing crawl use case reused by the monitoring service."""

    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult: ...


class TargetRunner(Protocol):
    """Manual target execution surface used by monitoring commands."""

    async def run_target(
        self, target_id: UUID, *, force: bool = False
    ) -> MonitoringRunResult | None: ...


class TargetRepository(Protocol):
    """Persistence boundary for monitoring configuration and scheduler state."""

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

    async def mark_succeeded(
        self, target_id: UUID, *, crawled_at: datetime, next_crawl_at: datetime
    ) -> None: ...

    async def mark_failed(
        self,
        target_id: UUID,
        *,
        failed_at: datetime,
        error: str,
        next_retry_at: datetime,
    ) -> None: ...


class SnapshotRepository(Protocol):
    """Persistence boundary for changed content versions."""

    async def create(self, snapshot: CrawlSnapshotCreate) -> CrawlSnapshot: ...

    async def get(self, snapshot_id: UUID) -> CrawlSnapshot | None: ...

    async def latest_by_target(self, target_id: UUID) -> dict[str, CrawlSnapshot]: ...

    async def list_versions(
        self, target_id: UUID, url: str
    ) -> builtins.list[CrawlSnapshot]: ...

    async def touch(
        self,
        snapshot_id: UUID,
        *,
        seen_at: datetime,
        etag: str | None,
        last_modified: str | None,
    ) -> None: ...


class ChangeRepository(Protocol):
    """Persistence boundary for meaningful change events."""

    async def create(self, change: CrawlChangeCreate) -> CrawlChange: ...

    async def recent(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> builtins.list[CrawlChange]: ...

    async def detail(self, change_id: UUID) -> tuple[CrawlChange, CrawlSnapshot] | None: ...


class MonitoringJobRepository(Protocol):
    """Persistence boundary for compact worker job status."""

    async def save(self, job: CrawlJobSummary) -> None: ...

    async def latest(self, target_id: UUID) -> CrawlJobSummary | None: ...


class MonitoringUnitOfWork(Protocol):
    """Transaction boundary spanning monitoring repositories."""

    targets: TargetRepository
    snapshots: SnapshotRepository
    changes: ChangeRepository
    jobs: MonitoringJobRepository

    async def __aenter__(self) -> MonitoringUnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    async def commit(self) -> None: ...


class MonitoringUnitOfWorkFactory(Protocol):
    """Create an isolated monitoring transaction."""

    def __call__(self) -> MonitoringUnitOfWork: ...
