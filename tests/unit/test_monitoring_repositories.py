from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from crawling_mcp.adapters.storage.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus, CrawlMode
from crawling_mcp.domain.monitoring import (
    CrawlChangeCreate,
    CrawlJobSummary,
    CrawlSnapshotCreate,
    CrawlTargetCreate,
)


@pytest.mark.asyncio
async def test_target_crud_and_due_claims_skip_disabled_or_leased_targets() -> None:
    store = InMemoryMonitoringStore()
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    due = await store.targets.create(
        CrawlTargetCreate(url="https://example.com/due", interval_seconds=60)
    )
    disabled = await store.targets.create(
        CrawlTargetCreate(
            url="https://example.com/disabled", interval_seconds=60, enabled=False
        )
    )

    claimed = await store.targets.claim_due(
        now=now, limit=10, lease_owner="worker-1", lease_seconds=30
    )

    assert [item.id for item in claimed] == [due.id]
    assert (await store.targets.get(due.id)).lease_owner == "worker-1"  # type: ignore[union-attr]
    assert (await store.targets.get(disabled.id)).enabled is False  # type: ignore[union-attr]
    assert await store.targets.claim_due(
        now=now, limit=10, lease_owner="worker-2", lease_seconds=30
    ) == []
    reclaimed = await store.targets.claim_due(
        now=now + timedelta(seconds=30),
        limit=10,
        lease_owner="worker-2",
        lease_seconds=30,
    )
    assert [item.id for item in reclaimed] == [due.id]


@pytest.mark.asyncio
async def test_target_success_and_failure_update_schedule_state() -> None:
    store = InMemoryMonitoringStore()
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    target = await store.targets.create(
        CrawlTargetCreate(url="https://example.com", interval_seconds=60)
    )

    await store.targets.mark_failed(
        target.id,
        failed_at=now,
        error="timeout",
        next_retry_at=now + timedelta(seconds=30),
    )
    failed = await store.targets.get(target.id)
    assert failed is not None
    assert failed.failure_count == 1
    assert failed.last_error == "timeout"
    assert failed.lease_owner is None

    await store.targets.mark_succeeded(
        target.id,
        crawled_at=now + timedelta(seconds=30),
        next_crawl_at=now + timedelta(seconds=90),
    )
    succeeded = await store.targets.get(target.id)
    assert succeeded is not None
    assert succeeded.failure_count == 0
    assert succeeded.next_retry_at is None
    assert succeeded.next_crawl_at == now + timedelta(seconds=90)


@pytest.mark.asyncio
async def test_snapshot_save_latest_and_touch_do_not_duplicate_content() -> None:
    store = InMemoryMonitoringStore()
    target = await store.targets.create(
        CrawlTargetCreate(url="https://example.com", interval_seconds=60)
    )
    first = await store.snapshots.create(
        CrawlSnapshotCreate(
            target_id=target.id,
            url="https://example.com/a",
            content_hash="a" * 64,
            title="A",
            content="body",
            etag='"one"',
        )
    )

    seen_at = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    await store.snapshots.touch(
        first.id, seen_at=seen_at, etag='"two"', last_modified="Mon, 10 Aug 2026 01:00:00 GMT"
    )
    latest = await store.snapshots.latest_by_target(target.id)

    assert list(latest) == ["https://example.com/a"]
    assert latest["https://example.com/a"].content == "body"
    assert latest["https://example.com/a"].last_seen_at == seen_at
    assert len(await store.snapshots.list_versions(target.id, "https://example.com/a")) == 1


@pytest.mark.asyncio
async def test_change_recent_and_detail_include_content_only_in_detail() -> None:
    store = InMemoryMonitoringStore()
    target = await store.targets.create(
        CrawlTargetCreate(url="https://example.com", interval_seconds=60)
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

    recent = await store.changes.recent(target_id=target.id, limit=10)
    detail = await store.changes.detail(change.id)

    assert recent == [change]
    assert not hasattr(recent[0], "content")
    assert detail is not None
    assert detail[1].content == "large body"


@pytest.mark.asyncio
async def test_monitoring_job_latest_status_is_stored_separately() -> None:
    store = InMemoryMonitoringStore()
    target = await store.targets.create(
        CrawlTargetCreate(
            url="https://example.com", interval_seconds=60, crawl_mode=CrawlMode.HTTP
        )
    )
    job = CrawlJobSummary(
        job_id=uuid4(),
        target_id=target.id,
        status=CrawlJobStatus.COMPLETED,
        checked=2,
        changed=1,
    )

    await store.jobs.save(job)

    assert await store.jobs.latest(target.id) == job
