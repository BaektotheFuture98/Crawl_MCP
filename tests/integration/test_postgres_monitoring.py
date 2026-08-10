from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from crawling_mcp.adapters.storage.postgres.crawl_repository import PostgresCrawlRepository
from crawling_mcp.adapters.storage.postgres.unit_of_work import PostgresMonitoringStore
from crawling_mcp.domain.enums import ChangeType
from crawling_mcp.domain.models import CrawlResult, PageItem
from crawling_mcp.domain.monitoring import (
    CrawlChangeCreate,
    CrawlSnapshotCreate,
    CrawlTargetCreate,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def require_storage_test() -> None:
    if os.getenv("CRAWLING_MCP_RUN_STORAGE_INTEGRATION") != "1":
        pytest.skip("set CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1")


async def test_postgres_target_snapshot_change_and_article_deduplication() -> None:
    require_storage_test()
    engine = create_async_engine(
        "postgresql+asyncpg://crawler:crawler@127.0.0.1:54329/crawling"
    )
    store = PostgresMonitoringStore(engine)
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE crawl_changes, crawl_snapshots, crawl_failures, "
                    "crawl_job_pages, crawl_jobs, crawl_targets, article CASCADE"
                )
            )

        async with store() as uow:
            target = await uow.targets.create(
                CrawlTargetCreate(url="https://example.com", interval_seconds=60)
            )
            await uow.commit()
        assert target.id.version == 7

        async with store() as uow:
            claimed = await uow.targets.claim_due(
                now=now, limit=1, lease_owner="integration", lease_seconds=60
            )
            await uow.commit()
        assert [item.id for item in claimed] == [target.id]

        create = CrawlSnapshotCreate(
            target_id=target.id,
            url="https://example.com/a",
            content_hash="a" * 64,
            title="A",
            content="body",
            etag='"v1"',
            collected_at=now,
        )
        async with store() as uow:
            snapshot = await uow.snapshots.create(create)
            duplicate = await uow.snapshots.create(create)
            change = await uow.changes.create(
                CrawlChangeCreate(
                    target_id=target.id,
                    change_type=ChangeType.NEW,
                    url=snapshot.url,
                    title=snapshot.title,
                    current_snapshot_id=snapshot.id,
                    detected_at=now,
                )
            )
            await uow.commit()

        assert snapshot.id.version == 7
        assert duplicate.id == snapshot.id
        assert change.id.version == 7
        async with engine.connect() as connection:
            article_count = (
                await connection.execute(sa.text("SELECT count(*) FROM article"))
            ).scalar_one()
        assert article_count == 1

        async with store() as uow:
            recent = await uow.changes.recent(target_id=target.id, limit=10)
            detail = await uow.changes.detail(change.id)
        assert recent == [change]
        assert detail is not None
        assert detail[1].content == "body"
    finally:
        await store.close()


async def test_postgres_crawl_repository_round_trip() -> None:
    require_storage_test()
    engine = create_async_engine(
        "postgresql+asyncpg://crawler:crawler@127.0.0.1:54329/crawling"
    )
    repository = PostgresCrawlRepository(engine)
    result = CrawlResult(start_url="https://example.com/manual")
    try:
        await repository.start_job(result)
        await repository.save_page(
            result.job_id,
            PageItem(
                url="https://example.com/manual",
                title="Manual",
                content="body",
                source="Example",
            ),
        )
        await repository.set_counts(
            result.job_id, visited_pages=1, succeeded_pages=1, failed_pages=0
        )
        await repository.complete_job(result.job_id)

        stored = await repository.get_job(result.job_id)

        assert stored is not None
        assert stored.items[0].title == "Manual"
        assert stored.items[0].source == "Example"
        assert stored.completed_at is not None
    finally:
        await repository.close()
