from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from crawling_mcp.adapters.article_extractors import (
    ArticleExtractorRegistry,
    StructuredArticleExtractor,
)
from crawling_mcp.adapters.storage.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.application.article_persistence_service import ArticlePersistenceService
from crawling_mcp.application.monitoring_service import MonitoringService
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
        self.calls: list[str] = []
        self.fail: set[str] = set()
        self.contents: dict[str, str] = {}

    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        self.calls.append(request.start_url)
        if request.start_url in self.fail:
            raise TimeoutError
        assert execution is not None
        assert execution.persist_result is False
        body = self.contents.get(request.start_url, "기사 본문")
        snapshot = PageSnapshot(
            url=request.start_url,
            html=f"<article><h1>기사 제목</h1><p>{body}</p></article>",
            headers={"etag": f'"{body}"'},
        )
        assert execution.page_handler is not None
        await execution.page_handler(snapshot, [PageItem(url=request.start_url)])
        return CrawlResult(
            job_id=execution.job_id,
            start_url=request.start_url,
            visited_pages=1,
            succeeded_pages=1,
        )


class BlockingRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        self.started.set()
        await self.release.wait()
        return await super().crawl_site(request, execution=execution)


def service(store: InMemoryMonitoringStore, runner: FakeRunner, now: datetime) -> MonitoringService:
    article_persistence = ArticlePersistenceService(uow_factory=store)
    extractors = ArticleExtractorRegistry(default=StructuredArticleExtractor())
    return MonitoringService(
        crawler=runner,
        article_extractors=extractors,
        article_persistence=article_persistence,
        uow_factory=store,
        clock=lambda: now,
        lease_seconds=60,
    )


@pytest.mark.asyncio
async def test_monitoring_crawl_extracts_and_aggregates_new_unchanged_updated() -> None:
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    store = InMemoryMonitoringStore()
    runner = FakeRunner()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/a", interval_seconds=60)
        )
    monitoring = service(store, runner, now)

    first = await monitoring.run_target(target.id, force=True)
    second = await monitoring.run_target(target.id, force=True)
    runner.contents[target.url] = "수정된 본문"
    third = await monitoring.run_target(target.id, force=True)

    assert first is not None and first.new_articles == 1
    assert second is not None and second.unchanged_articles == 1
    assert third is not None and third.updated_articles == 1
    async with store() as uow:
        articles = list(store._articles.values())
        runs = await uow.runs.latest(target_id=target.id)
    assert len(articles) == 1
    assert articles[0].content == "수정된 본문"
    assert len(runs) == 3


@pytest.mark.asyncio
async def test_due_targets_skip_disabled_and_isolate_failure() -> None:
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    store = InMemoryMonitoringStore()
    runner = FakeRunner()
    async with store() as uow:
        failed = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/fail", interval_seconds=60)
        )
        successful = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/ok", interval_seconds=60)
        )
        await uow.targets.create(
            CrawlTargetCreate(
                url="https://example.com/disabled", interval_seconds=60, enabled=False
            )
        )
    runner.fail.add(failed.url)

    results = await service(store, runner, now).run_due_targets(
        worker_id="worker-1", batch_size=10, lease_seconds=60
    )

    assert [item.target_id for item in results] == [successful.id]
    assert runner.calls == [failed.url, successful.url]
    async with store() as uow:
        failed_after = await uow.targets.get(failed.id)
    assert failed_after is not None
    assert failed_after.failure_count == 1
    assert failed_after.next_retry_at == now + timedelta(seconds=30)


@pytest.mark.asyncio
async def test_manual_runs_use_lease_and_do_not_overlap() -> None:
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    store = InMemoryMonitoringStore()
    runner = BlockingRunner()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/a", interval_seconds=60)
        )
    monitoring = service(store, runner, now)
    first = asyncio.create_task(monitoring.run_target(target.id, force=True))
    await runner.started.wait()

    second = await monitoring.run_target(target.id, force=True)
    runner.release.set()
    completed = await first

    assert second is None
    assert completed is not None
    assert runner.calls == [target.url]
