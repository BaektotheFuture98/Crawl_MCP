from __future__ import annotations

import asyncio
import builtins
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from crawling_mcp.domain.monitoring import (
    CrawlChange,
    CrawlChangeCreate,
    CrawlJobSummary,
    CrawlSnapshot,
    CrawlSnapshotCreate,
    CrawlTarget,
    CrawlTargetCreate,
)
from crawling_mcp.ports.monitoring import (
    ChangeRepository,
    MonitoringJobRepository,
    SnapshotRepository,
    TargetRepository,
)


class InMemoryMonitoringStore:
    """Concurrency-safe monitoring adapter used by tests and local development."""

    def __init__(self) -> None:
        self.targets = cast(TargetRepository, self)
        self.snapshots = cast(SnapshotRepository, self)
        self.changes = cast(ChangeRepository, self)
        self.jobs = cast(MonitoringJobRepository, self)
        self._targets: dict[UUID, CrawlTarget] = {}
        self._snapshots: dict[UUID, CrawlSnapshot] = {}
        self._changes: dict[UUID, CrawlChange] = {}
        self._jobs: dict[UUID, CrawlJobSummary] = {}
        self._lock = asyncio.Lock()

    async def create(
        self, value: CrawlTargetCreate | CrawlSnapshotCreate | CrawlChangeCreate
    ) -> CrawlTarget | CrawlSnapshot | CrawlChange:
        """Create one domain record with an adapter-owned test identifier."""
        async with self._lock:
            if isinstance(value, CrawlTargetCreate):
                target = CrawlTarget(id=uuid4(), **value.model_dump())
                self._targets[target.id] = target
                return target.model_copy(deep=True)
            if isinstance(value, CrawlSnapshotCreate):
                snapshot = CrawlSnapshot(
                    id=uuid4(),
                    article_id=uuid4(),
                    last_seen_at=value.collected_at,
                    **value.model_dump(),
                )
                self._snapshots[snapshot.id] = snapshot
                return snapshot.model_copy(deep=True)
            change = CrawlChange(id=uuid4(), **value.model_dump())
            self._changes[change.id] = change
            return change.model_copy(deep=True)

    async def get(self, record_id: UUID) -> CrawlTarget | CrawlSnapshot | None:
        """Get a target or snapshot by identifier."""
        async with self._lock:
            record = self._targets.get(record_id) or self._snapshots.get(record_id)
            return record.model_copy(deep=True) if record is not None else None

    async def list(
        self, *, enabled: bool | None = None, limit: int = 100
    ) -> builtins.list[CrawlTarget]:
        """List targets in creation order."""
        async with self._lock:
            values = sorted(self._targets.values(), key=lambda item: item.created_at)
            if enabled is not None:
                values = [item for item in values if item.enabled is enabled]
            return [item.model_copy(deep=True) for item in values[:limit]]

    async def save(self, value: CrawlTarget | CrawlJobSummary) -> CrawlTarget | None:
        """Save a target or compact monitoring job."""
        async with self._lock:
            if isinstance(value, CrawlJobSummary):
                self._jobs[value.job_id] = value.model_copy(deep=True)
                return None
            self._targets[value.id] = value.model_copy(deep=True)
            return value.model_copy(deep=True)

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_owner: str,
        lease_seconds: int,
    ) -> builtins.list[CrawlTarget]:
        """Atomically lease due targets."""
        async with self._lock:
            due = [item for item in self._targets.values() if item.is_due(now)]
            due.sort(key=lambda item: (item.next_retry_at or item.next_crawl_at or item.created_at))
            claimed: builtins.list[CrawlTarget] = []
            for target in due[:limit]:
                updated = target.model_copy(
                    update={
                        "lease_owner": lease_owner,
                        "lease_expires_at": now + timedelta(seconds=lease_seconds),
                        "updated_at": now,
                    }
                )
                self._targets[target.id] = updated
                claimed.append(updated.model_copy(deep=True))
            return claimed

    async def mark_succeeded(
        self, target_id: UUID, *, crawled_at: datetime, next_crawl_at: datetime
    ) -> None:
        """Release a lease and advance a successful target schedule."""
        async with self._lock:
            target = self._targets[target_id]
            self._targets[target_id] = target.model_copy(
                update={
                    "last_crawled_at": crawled_at,
                    "next_crawl_at": next_crawl_at,
                    "failure_count": 0,
                    "last_error": None,
                    "next_retry_at": None,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": crawled_at,
                }
            )

    async def mark_failed(
        self,
        target_id: UUID,
        *,
        failed_at: datetime,
        error: str,
        next_retry_at: datetime,
    ) -> None:
        """Release a lease and schedule an isolated retry."""
        async with self._lock:
            target = self._targets[target_id]
            self._targets[target_id] = target.model_copy(
                update={
                    "failure_count": target.failure_count + 1,
                    "last_error": error,
                    "last_failed_at": failed_at,
                    "next_retry_at": next_retry_at,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": failed_at,
                }
            )

    async def latest_by_target(self, target_id: UUID) -> dict[str, CrawlSnapshot]:
        """Return the newest changed version for every page URL."""
        async with self._lock:
            latest: dict[str, CrawlSnapshot] = {}
            for snapshot in sorted(
                self._snapshots.values(), key=lambda item: item.collected_at
            ):
                if snapshot.target_id == target_id:
                    latest[snapshot.url] = snapshot
            return {url: item.model_copy(deep=True) for url, item in latest.items()}

    async def list_versions(
        self, target_id: UUID, url: str
    ) -> builtins.list[CrawlSnapshot]:
        """List changed versions for one target/page."""
        async with self._lock:
            values = [
                item
                for item in self._snapshots.values()
                if item.target_id == target_id and item.url == url
            ]
            values.sort(key=lambda item: item.collected_at)
            return [item.model_copy(deep=True) for item in values]

    async def touch(
        self,
        snapshot_id: UUID,
        *,
        seen_at: datetime,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        """Record an unchanged observation without a new content row."""
        async with self._lock:
            snapshot = self._snapshots[snapshot_id]
            self._snapshots[snapshot_id] = snapshot.model_copy(
                update={
                    "last_seen_at": seen_at,
                    "etag": etag or snapshot.etag,
                    "last_modified": last_modified or snapshot.last_modified,
                }
            )

    async def recent(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> builtins.list[CrawlChange]:
        """Return compact newest-first change events."""
        async with self._lock:
            values = list(self._changes.values())
            if target_id is not None:
                values = [item for item in values if item.target_id == target_id]
            values.sort(key=lambda item: item.detected_at, reverse=True)
            return [item.model_copy(deep=True) for item in values[:limit]]

    async def detail(self, change_id: UUID) -> tuple[CrawlChange, CrawlSnapshot] | None:
        """Return one event with its current content version."""
        async with self._lock:
            change = self._changes.get(change_id)
            if change is None:
                return None
            snapshot = self._snapshots[change.current_snapshot_id]
            return change.model_copy(deep=True), snapshot.model_copy(deep=True)

    async def latest(self, target_id: UUID) -> CrawlJobSummary | None:
        """Return the newest compact job status for a target."""
        async with self._lock:
            values = [item for item in self._jobs.values() if item.target_id == target_id]
            if not values:
                return None
            latest = max(values, key=lambda item: item.started_at)
            return latest.model_copy(deep=True)

    async def __aenter__(self) -> InMemoryMonitoringStore:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def commit(self) -> None:
        """In-memory writes are immediately visible."""

    def __call__(self) -> InMemoryMonitoringStore:
        """Act as a unit-of-work factory for application tests."""
        return self
