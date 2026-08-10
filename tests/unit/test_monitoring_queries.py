from __future__ import annotations

from uuid import uuid4

import pytest

from crawling_mcp.adapters.storage.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.application.monitoring_query_service import MonitoringQueryService
from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus, CrawlMode
from crawling_mcp.domain.monitoring import (
    ConfigureTargetRequest,
    CrawlChangeCreate,
    CrawlJobSummary,
    CrawlSnapshotCreate,
)


class Runner:
    async def run_target(self, target_id: object, *, force: bool = False) -> None:
        assert force


@pytest.mark.asyncio
async def test_configure_target_creates_and_updates_only_supplied_fields() -> None:
    store = InMemoryMonitoringStore()
    service = MonitoringQueryService(
        uow_factory=store,
        monitoring=Runner(),  # type: ignore[arg-type]
    )
    created = await service.configure_target(
        ConfigureTargetRequest(
            url="https://example.com", interval_seconds=60, crawl_mode=CrawlMode.HTTP
        )
    )

    updated = await service.configure_target(
        ConfigureTargetRequest(target_id=created.id, enabled=False, interval_seconds=120)
    )

    assert updated.url == created.url
    assert updated.crawl_mode is CrawlMode.HTTP
    assert updated.enabled is False
    assert updated.interval_seconds == 120


@pytest.mark.asyncio
async def test_summary_queries_are_bounded_and_detail_is_explicit() -> None:
    store = InMemoryMonitoringStore()
    service = MonitoringQueryService(
        uow_factory=store,
        monitoring=Runner(),  # type: ignore[arg-type]
    )
    target = await service.configure_target(
        ConfigureTargetRequest(url="https://example.com", interval_seconds=60)
    )
    snapshot = await store.snapshots.create(
        CrawlSnapshotCreate(
            target_id=target.id,
            url="https://example.com/a",
            content_hash="a" * 64,
            title="A",
            content="large body",
        )
    )
    change = await store.changes.create(
        CrawlChangeCreate(
            target_id=target.id,
            change_type=ChangeType.NEW,
            url=snapshot.url,
            title=snapshot.title,
            current_snapshot_id=snapshot.id,
        )
    )
    job = CrawlJobSummary(
        job_id=uuid4(),
        target_id=target.id,
        status=CrawlJobStatus.COMPLETED,
        checked=100,
        changed=1,
        new=1,
    )
    await store.jobs.save(job)

    recent = await service.get_recent_changes(target_id=target.id, limit=1)
    status = await service.get_crawl_status(target_id=target.id, limit=10)
    detail = await service.get_change_detail(change.id)

    assert recent == [change]
    assert "content" not in recent[0].model_dump()
    assert status == [job]
    assert detail is not None
    assert detail.snapshot.content == "large body"
