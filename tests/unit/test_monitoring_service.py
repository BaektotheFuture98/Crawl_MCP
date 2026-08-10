from __future__ import annotations

from datetime import UTC, datetime

import pytest

from crawling_mcp.adapters.storage.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.application.monitoring_service import MonitoringService
from crawling_mcp.domain.enums import ChangeType
from crawling_mcp.domain.models import (
    CrawlExecution,
    CrawlRequest,
    CrawlResult,
    PageItem,
    PageSnapshot,
)
from crawling_mcp.domain.monitoring import CrawlTargetCreate


class FakeRunner:
    def __init__(self) -> None:
        self.content_by_url: dict[str, str | Exception] = {}
        self.calls: list[str] = []
        self.not_modified: set[str] = set()

    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        assert execution is not None
        self.calls.append(request.start_url)
        value = self.content_by_url.get(request.start_url, "body")
        if isinstance(value, Exception):
            raise value
        snapshot = PageSnapshot(
            url=request.start_url,
            html="",
            status_code=304 if request.start_url in self.not_modified else 200,
            not_modified=request.start_url in self.not_modified,
            headers={"etag": '"v1"', "last-modified": "Mon, 10 Aug 2026 01:00:00 GMT"},
        )
        if snapshot.not_modified:
            assert execution.not_modified_handler is not None
            await execution.not_modified_handler(snapshot)
            items: list[PageItem] = []
        else:
            items = [PageItem(url=request.start_url, title="Title", content=value)]
            assert execution.page_handler is not None
            await execution.page_handler(snapshot, items)
        return CrawlResult(
            job_id=execution.job_id,
            start_url=request.start_url,
            visited_pages=1,
            succeeded_pages=1,
            items=items,
        )


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 10, 1, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_monitoring_service_stores_new_unchanged_and_updated_versions(now: datetime) -> None:
    store = InMemoryMonitoringStore()
    runner = FakeRunner()
    target = await store.targets.create(
        CrawlTargetCreate(url="https://example.com/a", interval_seconds=60)
    )
    service = MonitoringService(crawler=runner, uow_factory=store, clock=lambda: now)

    first = await service.run_target(target.id, force=True)
    second = await service.run_target(target.id, force=True)
    runner.content_by_url[target.url] = "changed"
    third = await service.run_target(target.id, force=True)

    assert first is not None and first.new == 1
    assert second is not None and second.unchanged == 1
    assert third is not None and third.updated == 1
    versions = await store.snapshots.list_versions(target.id, target.url)
    changes = await store.changes.recent(target_id=target.id, limit=10)
    assert len(versions) == 2
    assert {change.change_type for change in changes} == {
        ChangeType.NEW,
        ChangeType.UPDATED,
    }


@pytest.mark.asyncio
async def test_not_modified_touches_snapshot_without_extracting_or_hashing(now: datetime) -> None:
    store = InMemoryMonitoringStore()
    runner = FakeRunner()
    target = await store.targets.create(
        CrawlTargetCreate(url="https://example.com/a", interval_seconds=60)
    )
    service = MonitoringService(crawler=runner, uow_factory=store, clock=lambda: now)
    await service.run_target(target.id, force=True)
    runner.not_modified.add(target.url)

    result = await service.run_target(target.id, force=True)

    assert result is not None
    assert result.unchanged == 1
    assert len(await store.snapshots.list_versions(target.id, target.url)) == 1


@pytest.mark.asyncio
async def test_disabled_target_is_not_run(now: datetime) -> None:
    store = InMemoryMonitoringStore()
    runner = FakeRunner()
    target = await store.targets.create(
        CrawlTargetCreate(url="https://example.com/a", interval_seconds=60, enabled=False)
    )
    service = MonitoringService(crawler=runner, uow_factory=store, clock=lambda: now)

    assert await service.run_target(target.id) is None
    assert runner.calls == []


@pytest.mark.asyncio
async def test_run_due_targets_isolates_failure_and_continues(now: datetime) -> None:
    store = InMemoryMonitoringStore()
    runner = FakeRunner()
    targets = [
        await store.targets.create(
            CrawlTargetCreate(url=f"https://example.com/{name}", interval_seconds=60)
        )
        for name in ("a", "b", "c")
    ]
    runner.content_by_url[targets[1].url] = TimeoutError("slow")
    service = MonitoringService(
        crawler=runner,
        uow_factory=store,
        clock=lambda: now,
        retry_base_seconds=30,
        retry_max_seconds=300,
    )

    results = await service.run_due_targets(worker_id="worker-1", batch_size=10, lease_seconds=60)

    assert [result.target_id for result in results] == [targets[0].id, targets[2].id]
    failed = await store.targets.get(targets[1].id)
    assert failed is not None
    assert failed.failure_count == 1
    assert failed.last_error == "TimeoutError"
    assert runner.calls == [target.url for target in targets]
