from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from crawling_mcp.adapters.article_extractors import (
    ArticleExtractorRegistry,
    StructuredArticleExtractor,
)
from crawling_mcp.adapters.storage.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.application.article_persistence_service import ArticlePersistenceService
from crawling_mcp.application.monitoring_service import LeaseLostError, MonitoringService
from crawling_mcp.domain.enums import CrawlJobStatus
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
        assert execution.collect_items is False
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


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class InspectingRunner(FakeRunner):
    def __init__(self, store: InMemoryMonitoringStore) -> None:
        super().__init__()
        self._store = store
        self.persisted_before_return = False

    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        result = await super().crawl_site(request, execution=execution)
        self.persisted_before_return = bool(self._store._articles)
        return result


class TakeoverRunner(FakeRunner):
    def __init__(
        self,
        store: InMemoryMonitoringStore,
        target_id: UUID,
        clock: MutableClock,
    ) -> None:
        super().__init__()
        self._store = store
        self._target_id = target_id
        self._clock = clock

    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        self._clock.value += timedelta(seconds=2)
        async with self._store() as uow:
            reclaimed = await uow.targets.claim(
                self._target_id,
                now=self._clock(),
                lease_owner="replacement-worker",
                lease_seconds=60,
                force=True,
            )
        assert reclaimed is not None
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


@pytest.mark.asyncio
async def test_due_targets_claim_next_only_after_current_finishes() -> None:
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    store = InMemoryMonitoringStore()
    runner = BlockingRunner()
    async with store() as uow:
        first = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/first", interval_seconds=60)
        )
        second = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/second", interval_seconds=60)
        )

    task = asyncio.create_task(
        service(store, runner, now).run_due_targets(
            worker_id="worker-1", batch_size=2, lease_seconds=60
        )
    )
    await runner.started.wait()
    async with store() as uow:
        first_while_running = await uow.targets.get(first.id)
        second_while_waiting = await uow.targets.get(second.id)

    assert first_while_running is not None
    assert first_while_running.lease_owner == "worker-1"
    assert second_while_waiting is not None
    assert second_while_waiting.lease_owner is None

    runner.release.set()
    results = await task
    assert [result.target_id for result in results] == [first.id, second.id]


@pytest.mark.asyncio
async def test_long_running_target_renews_its_lease() -> None:
    started_at = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    clock = MutableClock(started_at)
    store = InMemoryMonitoringStore()
    runner = BlockingRunner()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/slow", interval_seconds=60)
        )
    monitoring = MonitoringService(
        crawler=runner,
        article_extractors=ArticleExtractorRegistry(default=StructuredArticleExtractor()),
        article_persistence=ArticlePersistenceService(uow_factory=store),
        uow_factory=store,
        clock=clock,
        lease_seconds=1,
        heartbeat_interval_seconds=0.01,
    )
    task = asyncio.create_task(monitoring.run_target(target.id, force=True))
    await runner.started.wait()

    clock.value = started_at + timedelta(milliseconds=750)
    await asyncio.sleep(0.03)
    async with store() as uow:
        takeover = await uow.targets.claim(
            target.id,
            now=started_at + timedelta(milliseconds=1100),
            lease_owner="worker-2",
            lease_seconds=1,
            force=True,
        )

    assert takeover is None
    runner.release.set()
    assert await task is not None


@pytest.mark.asyncio
async def test_page_observation_is_persisted_before_crawl_returns() -> None:
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    store = InMemoryMonitoringStore()
    runner = InspectingRunner(store)
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/stream", interval_seconds=60)
        )

    result = await service(store, runner, now).run_target(target.id, force=True)

    assert result is not None and result.new_articles == 1
    assert runner.persisted_before_return


@pytest.mark.asyncio
async def test_lost_lease_blocks_finalization_and_next_claim_recovers_run() -> None:
    started_at = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    clock = MutableClock(started_at)
    store = InMemoryMonitoringStore()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/takeover", interval_seconds=60)
        )
    stale_monitoring = MonitoringService(
        crawler=TakeoverRunner(store, target.id, clock),
        article_extractors=ArticleExtractorRegistry(default=StructuredArticleExtractor()),
        article_persistence=ArticlePersistenceService(uow_factory=store),
        uow_factory=store,
        clock=clock,
        lease_seconds=1,
        heartbeat_interval_seconds=60,
    )

    with pytest.raises(LeaseLostError):
        await stale_monitoring.run_target(target.id, force=True)

    async with store() as uow:
        after_takeover = await uow.targets.get(target.id)
        stale_runs = await uow.runs.latest(target_id=target.id)
    assert after_takeover is not None
    assert after_takeover.lease_owner == "replacement-worker"
    assert after_takeover.failure_count == 0
    assert stale_runs[0].status is CrawlJobStatus.RUNNING

    clock.value += timedelta(seconds=61)
    recovered = await service(store, FakeRunner(), clock()).run_target(target.id, force=True)

    assert recovered is not None
    async with store() as uow:
        runs = await uow.runs.latest(target_id=target.id)
    assert [run.status for run in runs] == [
        CrawlJobStatus.COMPLETED,
        CrawlJobStatus.FAILED,
    ]
    assert runs[1].error == "lease_expired"


@pytest.mark.asyncio
async def test_heartbeat_storage_failure_fails_closed() -> None:
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    store = InMemoryMonitoringStore()
    runner = BlockingRunner()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/heartbeat", interval_seconds=60)
        )

    async def fail_renewal(*args: object, **kwargs: object) -> bool:
        del args, kwargs
        raise ConnectionError("storage unavailable")

    store.targets.renew_lease = fail_renewal  # type: ignore[method-assign]
    monitoring = MonitoringService(
        crawler=runner,
        article_extractors=ArticleExtractorRegistry(default=StructuredArticleExtractor()),
        article_persistence=ArticlePersistenceService(uow_factory=store),
        uow_factory=store,
        clock=lambda: now,
        lease_seconds=60,
        heartbeat_interval_seconds=0.01,
    )
    task = asyncio.create_task(monitoring.run_target(target.id, force=True))
    await runner.started.wait()
    await asyncio.sleep(0.03)
    runner.release.set()

    with pytest.raises(LeaseLostError):
        await task

    async with store() as uow:
        failed_target = await uow.targets.get(target.id)
        runs = await uow.runs.latest(target_id=target.id)
    assert failed_target is not None and failed_target.failure_count == 1
    assert runs[0].status is CrawlJobStatus.FAILED
