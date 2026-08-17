from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from crawling_mcp.adapters.outbound.extraction.articles import ArticleExtractorRegistry
from crawling_mcp.adapters.outbound.persistence.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.application.article_collection_service import (
    ArticleCollectionService,
    IncompleteCollectionError,
    LeaseLostError,
)
from crawling_mcp.domain.articles import ArticleCandidate
from crawling_mcp.domain.models import CrawlExecution, CrawlRequest, CrawlResult, PageSnapshot
from crawling_mcp.domain.monitoring import CrawlTargetCreate


class FakeExtractor:
    name = "fake"

    def __init__(self, candidates: list[ArticleCandidate]) -> None:
        self.candidates = candidates

    async def extract_articles(self, snapshot: PageSnapshot) -> list[ArticleCandidate]:
        del snapshot
        return list(self.candidates)


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail: set[str] = set()

    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        self.calls.append(request.start_url)
        if request.start_url in self.fail:
            raise TimeoutError
        assert execution is not None and execution.page_handler is not None
        await execution.page_handler(PageSnapshot(url=request.start_url, html="<html></html>"), [])
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


class PartialFailureRunner(FakeRunner):
    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        result = await super().crawl_site(request, execution=execution)
        return result.model_copy(update={"failed_pages": 1})


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def candidate(url: str, published_at: datetime | None, content: str = "본문") -> ArticleCandidate:
    return ArticleCandidate(
        url=url,
        title="기사",
        content=content,
        published_at=published_at,
    )


def service(
    store: InMemoryMonitoringStore,
    runner: FakeRunner,
    clock: MutableClock,
    candidates: list[ArticleCandidate],
    lease_seconds: int = 60,
    heartbeat_interval_seconds: float | None = None,
) -> ArticleCollectionService:
    return ArticleCollectionService(
        crawler=runner,
        article_extractors=ArticleExtractorRegistry(default=FakeExtractor(candidates)),
        uow_factory=store,
        clock=clock,
        lease_seconds=lease_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )


@pytest.mark.asyncio
async def test_collects_only_in_window_and_advances_watermark() -> None:
    created_at = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    now = created_at + timedelta(minutes=10)
    clock = MutableClock(now)
    store = InMemoryMonitoringStore()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(
                url="https://example.com/news",
                interval_seconds=60,
                discovery_lag_seconds=30,
                discovery_overlap_seconds=60,
            )
        )
        await uow.targets.save(
            target.model_copy(update={"created_at": created_at, "updated_at": created_at})
        )
    candidates = [
        candidate("https://example.com/new?utm_source=x", now - timedelta(minutes=1)),
        candidate("https://example.com/too-new", now - timedelta(seconds=10)),
        candidate("https://example.com/no-date", None),
    ]

    result = await service(store, FakeRunner(), clock, candidates).run_target(target.id, force=True)

    assert result is not None
    assert result.discovered_articles == result.inserted_articles == 1
    assert result.duplicate_articles == 0
    assert [item.url for item in store._articles.values()] == ["https://example.com/new"]
    async with store() as uow:
        stored = await uow.targets.get(target.id)
    assert stored is not None
    assert stored.discovery_watermark_at == now - timedelta(seconds=30)


@pytest.mark.asyncio
async def test_overlap_reobservation_is_duplicate_and_does_not_update_article() -> None:
    created_at = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    clock = MutableClock(created_at + timedelta(minutes=10))
    store = InMemoryMonitoringStore()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(
                url="https://example.com/news",
                interval_seconds=60,
                discovery_lag_seconds=0,
                discovery_overlap_seconds=300,
            )
        )
        await uow.targets.save(
            target.model_copy(update={"created_at": created_at, "updated_at": created_at})
        )
    first_candidate = candidate(
        "https://example.com/article", clock.value - timedelta(minutes=1), "원문"
    )
    first = await service(store, FakeRunner(), clock, [first_candidate]).run_target(
        target.id, force=True
    )
    clock.value += timedelta(minutes=1)
    edited = first_candidate.model_copy(update={"content": "수정 본문"})
    second = await service(store, FakeRunner(), clock, [edited]).run_target(target.id, force=True)

    assert first is not None and first.inserted_articles == 1
    assert second is not None and second.duplicate_articles == 1
    assert len(store._articles) == 1
    assert next(iter(store._articles.values())).content == "원문"
    assert len(store._discoveries) == 1


@pytest.mark.asyncio
async def test_manual_runs_use_lease_and_do_not_overlap() -> None:
    now = datetime(2026, 8, 10, 1, 10, tzinfo=UTC)
    clock = MutableClock(now)
    store = InMemoryMonitoringStore()
    runner = BlockingRunner()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/news", interval_seconds=60)
        )
    collection = service(store, runner, clock, [])
    first = asyncio.create_task(collection.run_target(target.id, force=True))
    await runner.started.wait()

    second = await collection.run_target(target.id, force=True)
    runner.release.set()

    assert second is None
    assert await first is not None


@pytest.mark.asyncio
async def test_failed_target_uses_backoff_without_advancing_watermark() -> None:
    now = datetime(2026, 8, 10, 1, 10, tzinfo=UTC)
    clock = MutableClock(now)
    store = InMemoryMonitoringStore()
    runner = FakeRunner()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/fail", interval_seconds=60)
        )
    runner.fail.add(target.url)

    with pytest.raises(TimeoutError):
        await service(store, runner, clock, []).run_target(target.id, force=True)

    async with store() as uow:
        stored = await uow.targets.get(target.id)
    assert stored is not None
    assert stored.failure_count == 1
    assert stored.next_retry_at == now + timedelta(seconds=30)
    assert stored.discovery_watermark_at is None


@pytest.mark.asyncio
async def test_partial_page_failure_does_not_advance_watermark() -> None:
    now = datetime(2026, 8, 10, 1, 10, tzinfo=UTC)
    clock = MutableClock(now)
    store = InMemoryMonitoringStore()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/partial", interval_seconds=60)
        )

    with pytest.raises(IncompleteCollectionError):
        await service(store, PartialFailureRunner(), clock, []).run_target(target.id, force=True)

    async with store() as uow:
        stored = await uow.targets.get(target.id)
        runs = await uow.runs.latest(target_id=target.id)
    assert stored is not None and stored.discovery_watermark_at is None
    assert runs[0].failed_pages == 1


class TakeoverRunner(FakeRunner):
    def __init__(
        self, store: InMemoryMonitoringStore, target_id: UUID, clock: MutableClock
    ) -> None:
        super().__init__()
        self.store = store
        self.target_id = target_id
        self.clock = clock

    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        self.clock.value += timedelta(seconds=2)
        async with self.store() as uow:
            assert await uow.targets.claim(
                self.target_id,
                now=self.clock(),
                lease_owner="replacement",
                lease_seconds=60,
                force=True,
            )
        return await super().crawl_site(request, execution=execution)


@pytest.mark.asyncio
async def test_lost_lease_cannot_finalize_run_or_watermark() -> None:
    now = datetime(2026, 8, 10, 1, 10, tzinfo=UTC)
    clock = MutableClock(now)
    store = InMemoryMonitoringStore()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/news", interval_seconds=60)
        )
    runner = TakeoverRunner(store, target.id, clock)
    collection = service(
        store,
        runner,
        clock,
        [],
        lease_seconds=1,
        heartbeat_interval_seconds=60,
    )

    with pytest.raises(LeaseLostError):
        await collection.run_target(target.id, force=True)

    async with store() as uow:
        stored = await uow.targets.get(target.id)
    assert stored is not None
    assert stored.lease_owner == "replacement"
    assert stored.discovery_watermark_at is None
