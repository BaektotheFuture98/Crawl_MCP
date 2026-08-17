from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from crawling_mcp.adapters.article_extractors import (
    ArticleExtractorRegistry,
    StructuredArticleExtractor,
)
from crawling_mcp.adapters.storage.postgres import PostgresMonitoringStore
from crawling_mcp.application.article_persistence_service import ArticlePersistenceService
from crawling_mcp.application.monitoring_service import MonitoringService
from crawling_mcp.domain.articles import ArticleCandidate, ArticleObservation
from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus
from crawling_mcp.domain.models import (
    CrawlExecution,
    CrawlRequest,
    CrawlResult,
    PageItem,
    PageSnapshot,
)
from crawling_mcp.domain.monitoring import CrawlRunCreate, CrawlTargetCreate

_DSN = "postgresql+asyncpg://crawler:crawler@127.0.0.1:54329/crawling"


def require_storage_test() -> None:
    if os.getenv("CRAWLING_MCP_RUN_STORAGE_INTEGRATION") != "1":
        pytest.skip("set CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1")


async def clean(engine: object) -> None:
    async with engine.begin() as connection:  # type: ignore[union-attr]
        await connection.execute(
            sa.text("TRUNCATE article_crawl_state, crawl_run, crawl_target, article CASCADE")
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_article_persistence_uses_one_uuidv7_article_row() -> None:
    require_storage_test()
    engine = create_async_engine(_DSN)
    store = PostgresMonitoringStore(engine)
    try:
        await clean(engine)
        async with store() as uow:
            target = await uow.targets.create(
                CrawlTargetCreate(url="https://example.com", interval_seconds=60)
            )
            await uow.commit()
        service = ArticlePersistenceService(uow_factory=store)
        now = datetime(2026, 8, 10, tzinfo=UTC)
        first = ArticleCandidate(
            url="https://example.com/a",
            title="기사 제목",
            content="기사 본문",
            reporter="홍길동 기자",
            publisher="동아일보",
            published_at=now,
        )

        new = await service.persist(
            target_id=target.id,
            observation=ArticleObservation(candidate=first, etag='"v1"'),
            observed_at=now,
        )
        unchanged = await service.persist(
            target_id=target.id,
            observation=ArticleObservation(candidate=first, etag='"v1"'),
            observed_at=now,
        )
        updated = await service.persist(
            target_id=target.id,
            observation=ArticleObservation(
                candidate=first.model_copy(update={"content": "수정 본문"}), etag='"v2"'
            ),
            observed_at=now,
        )

        assert [new.change_type, unchanged.change_type, updated.change_type] == [
            ChangeType.NEW,
            ChangeType.UNCHANGED,
            ChangeType.UPDATED,
        ]
        assert new.article_id.version == 7
        assert target.id.version == 7
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text("SELECT count(*) AS count, max(ar_content) AS body FROM article")
                )
            ).one()
        assert row.count == 1
        assert row.body == "수정 본문"
    finally:
        await store.close()


class Runner:
    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        assert execution is not None and execution.persist_result is False
        snapshot = PageSnapshot(
            url="https://example.com/a",
            html="<article><h1>기사 제목</h1><p>기사 본문</p></article>",
            headers={"etag": '"v1"'},
        )
        assert execution.page_handler is not None
        await execution.page_handler(snapshot, [PageItem(url=snapshot.url)])
        return CrawlResult(
            job_id=execution.job_id,
            start_url=request.start_url,
            visited_pages=1,
            succeeded_pages=1,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_monitoring_service_records_article_state_and_run() -> None:
    require_storage_test()
    engine = create_async_engine(_DSN)
    store = PostgresMonitoringStore(engine)
    try:
        await clean(engine)
        async with store() as uow:
            target = await uow.targets.create(
                CrawlTargetCreate(url="https://example.com", interval_seconds=60)
            )
            await uow.commit()
        persistence = ArticlePersistenceService(uow_factory=store)
        monitoring = MonitoringService(
            crawler=Runner(),
            article_extractors=ArticleExtractorRegistry(default=StructuredArticleExtractor()),
            article_persistence=persistence,
            uow_factory=store,
        )

        result = await monitoring.run_target(target.id, force=True)

        assert result is not None and result.new_articles == 1
        assert result.crawl_run_id.version == 7
        async with store() as uow:
            runs = await uow.runs.latest(target_id=target.id)
            changes = await uow.states.recent_changes(target_id=target.id)
        assert runs[0].new_articles == 1
        assert changes[0].title == "기사 제목"
        assert "content" not in changes[0].model_dump()
    finally:
        await store.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_targets_share_article_but_keep_independent_state() -> None:
    require_storage_test()
    engine = create_async_engine(_DSN)
    store = PostgresMonitoringStore(engine)
    try:
        await clean(engine)
        async with store() as uow:
            first_target = await uow.targets.create(
                CrawlTargetCreate(url="https://example.com/feed-a", interval_seconds=60)
            )
            second_target = await uow.targets.create(
                CrawlTargetCreate(url="https://example.com/feed-b", interval_seconds=60)
            )
            await uow.commit()
        service = ArticlePersistenceService(uow_factory=store)
        candidate = ArticleCandidate(
            url="https://example.com/shared",
            title="공유 기사",
            content="공유 본문",
        )
        observed_at = datetime(2026, 8, 10, tzinfo=UTC)

        first, second = await asyncio.gather(
            service.persist(
                target_id=first_target.id,
                observation=ArticleObservation(candidate=candidate, etag='"a"'),
                observed_at=observed_at,
            ),
            service.persist(
                target_id=second_target.id,
                observation=ArticleObservation(candidate=candidate, etag='"b"'),
                observed_at=observed_at,
            ),
        )

        assert first.article_id == second.article_id
        assert first.change_type is ChangeType.NEW
        assert second.change_type is ChangeType.NEW
        async with engine.connect() as connection:
            article_count = await connection.scalar(sa.text("SELECT count(*) FROM article"))
            state_rows = (
                await connection.execute(
                    sa.text(
                        "SELECT target_id, etag FROM article_crawl_state "
                        "WHERE article_id = :article_id ORDER BY target_id"
                    ),
                    {"article_id": first.article_id},
                )
            ).all()
        assert article_count == 1
        assert {row.target_id for row in state_rows} == {first_target.id, second_target.id}
        assert {row.etag for row in state_rows} == {'"a"', '"b"'}
    finally:
        await store.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_lease_fencing_and_stale_run_recovery() -> None:
    require_storage_test()
    engine = create_async_engine(_DSN)
    store = PostgresMonitoringStore(engine)
    try:
        await clean(engine)
        started_at = datetime(2026, 8, 10, tzinfo=UTC)
        async with store() as uow:
            target = await uow.targets.create(
                CrawlTargetCreate(url="https://example.com/fenced", interval_seconds=60)
            )
            first = await uow.targets.claim(
                target.id,
                now=started_at,
                lease_owner="worker-a",
                lease_seconds=30,
                force=True,
            )
            stale_run = await uow.runs.create(
                CrawlRunCreate(target_id=target.id, started_at=started_at)
            )
            await uow.commit()
        assert first is not None

        reclaimed_at = started_at + timedelta(seconds=31)
        async with store() as uow:
            second = await uow.targets.claim(
                target.id,
                now=reclaimed_at,
                lease_owner="worker-b",
                lease_seconds=30,
                force=True,
            )
            reconciled = await uow.runs.fail_running(
                target.id,
                completed_at=reclaimed_at,
                error="lease_expired",
            )
            stale_renewed = await uow.targets.renew_lease(
                target.id,
                lease_owner="worker-a",
                now=reclaimed_at,
                lease_seconds=30,
            )
            stale_finalized = await uow.targets.mark_succeeded(
                target.id,
                lease_owner="worker-a",
                crawled_at=reclaimed_at,
                next_crawl_at=reclaimed_at + timedelta(seconds=60),
            )
            run_overwritten = await uow.runs.save_terminal(
                stale_run.model_copy(
                    update={
                        "status": CrawlJobStatus.COMPLETED,
                        "completed_at": reclaimed_at,
                    }
                )
            )
            owner_renewed = await uow.targets.renew_lease(
                target.id,
                lease_owner="worker-b",
                now=reclaimed_at,
                lease_seconds=30,
            )
            await uow.commit()

        assert second is not None
        assert reconciled == 1
        assert not stale_renewed
        assert not stale_finalized
        assert not run_overwritten
        assert owner_renewed
        async with store() as uow:
            runs = await uow.runs.latest(target_id=target.id)
        assert runs[0].status is CrawlJobStatus.FAILED
        assert runs[0].error == "lease_expired"
    finally:
        await store.close()
