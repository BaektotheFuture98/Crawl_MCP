from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import structlog

from crawling_mcp.application.article_persistence_service import ArticlePersistenceService
from crawling_mcp.domain.articles import ArticleObservation
from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus
from crawling_mcp.domain.models import (
    CrawlCacheEntry,
    CrawlExecution,
    PageItem,
    PageSnapshot,
    utc_now,
)
from crawling_mcp.domain.monitoring import (
    CrawlRun,
    CrawlRunCreate,
    CrawlTarget,
    MonitoringRunResult,
)
from crawling_mcp.domain.policies import normalize_url
from crawling_mcp.ports.extractor import ArticleExtractorResolver
from crawling_mcp.ports.monitoring import CrawlRunner, MonitoringUnitOfWorkFactory


class MonitoringService:
    """Run claimed targets, extract articles, and persist only latest article state."""

    def __init__(
        self,
        *,
        crawler: CrawlRunner,
        article_extractors: ArticleExtractorResolver,
        article_persistence: ArticlePersistenceService,
        uow_factory: MonitoringUnitOfWorkFactory,
        clock: Callable[[], datetime] = utc_now,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 3600,
        lease_seconds: int = 600,
    ) -> None:
        self._crawler = crawler
        self._article_extractors = article_extractors
        self._article_persistence = article_persistence
        self._uow_factory = uow_factory
        self._clock = clock
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._lease_seconds = lease_seconds
        self._log = structlog.get_logger(__name__)

    async def run_target(
        self, target_id: UUID, *, force: bool = False
    ) -> MonitoringRunResult | None:
        """Lease and run one target; manual and scheduled calls share this boundary."""
        now = self._clock()
        owner = f"manual-{uuid4()}"
        async with self._uow_factory() as uow:
            target = await uow.targets.claim(
                target_id,
                now=now,
                lease_owner=owner,
                lease_seconds=self._lease_seconds,
                force=force,
            )
            await uow.commit()
        if target is None:
            return None
        return await self._run_claimed_target(target)

    async def _run_claimed_target(self, target: CrawlTarget) -> MonitoringRunResult:
        now = self._clock()
        async with self._uow_factory() as uow:
            run = await uow.runs.create(CrawlRunCreate(target_id=target.id, started_at=now))
            states = await uow.states.list_by_target(target.id)
            await uow.commit()

        observed: list[PageSnapshot] = []
        not_modified: list[PageSnapshot] = []

        async def observe(snapshot: PageSnapshot, items: list[PageItem]) -> None:
            del items
            observed.append(snapshot.model_copy(deep=True))

        async def observe_not_modified(snapshot: PageSnapshot) -> None:
            not_modified.append(snapshot.model_copy(deep=True))

        execution = CrawlExecution(
            job_id=run.id,
            persist_result=False,
            cache_entries={
                state.url: CrawlCacheEntry(
                    url=state.url,
                    etag=state.etag,
                    last_modified=state.last_modified,
                )
                for state in states
            },
            page_handler=observe,
            not_modified_handler=observe_not_modified,
        )
        started = time.perf_counter()
        self._log.info(
            "crawl_target_started",
            target_id=str(target.id),
            crawl_run_id=str(run.id),
            url=target.url,
            crawl_mode=target.crawl_mode.value,
        )
        try:
            crawl_result = await self._crawler.crawl_site(
                target.to_crawl_request(), execution=execution
            )
            counters = {ChangeType.NEW: 0, ChangeType.UPDATED: 0, ChangeType.UNCHANGED: 0}
            processed_urls: set[str] = set()
            seen_at = self._clock()

            for snapshot in not_modified:
                url = normalize_url(snapshot.url, remove_tracking=True)
                async with self._uow_factory() as uow:
                    state = await uow.states.find_by_url(url)
                    if state is None:
                        continue
                    await uow.states.save(
                        state.model_copy(
                            update={
                                "last_seen_at": seen_at,
                                "etag": snapshot.headers.get("etag") or state.etag,
                                "last_modified": (
                                    snapshot.headers.get("last-modified") or state.last_modified
                                ),
                            }
                        )
                    )
                    await uow.commit()
                processed_urls.add(url)
                counters[ChangeType.UNCHANGED] += 1

            extraction_failures = 0
            for snapshot in observed:
                domain = (urlsplit(snapshot.url).hostname or "").lower().rstrip(".")
                extractor = self._article_extractors.get(domain)
                try:
                    candidates = await extractor.extract_articles(snapshot)
                except Exception as error:
                    extraction_failures += 1
                    self._log.warning(
                        "article_extraction_failed",
                        target_id=str(target.id),
                        crawl_run_id=str(run.id),
                        url=snapshot.url,
                        extractor=extractor.name,
                        error_type=type(error).__name__,
                    )
                    continue
                for candidate in candidates:
                    canonical = normalize_url(candidate.url, remove_tracking=True)
                    if canonical in processed_urls:
                        continue
                    processed_urls.add(canonical)
                    persistence_result = await self._article_persistence.persist(
                        target_id=target.id,
                        observation=ArticleObservation(
                            candidate=candidate,
                            etag=snapshot.headers.get("etag"),
                            last_modified=snapshot.headers.get("last-modified"),
                        ),
                        observed_at=seen_at,
                    )
                    counters[persistence_result.change_type] += 1

            completed_at = self._clock()
            failed_pages = crawl_result.failed_pages + extraction_failures
            completed = run.model_copy(
                update={
                    "status": CrawlJobStatus.COMPLETED,
                    "visited_pages": crawl_result.visited_pages,
                    "new_articles": counters[ChangeType.NEW],
                    "updated_articles": counters[ChangeType.UPDATED],
                    "unchanged_articles": counters[ChangeType.UNCHANGED],
                    "failed_pages": failed_pages,
                    "completed_at": completed_at,
                }
            )
            async with self._uow_factory() as uow:
                await uow.runs.save(completed)
                await uow.targets.mark_succeeded(
                    target.id,
                    crawled_at=completed_at,
                    next_crawl_at=completed_at + timedelta(seconds=target.interval_seconds),
                )
                await uow.commit()
            monitoring_result = MonitoringRunResult(
                target_id=target.id,
                crawl_run_id=run.id,
                visited_pages=crawl_result.visited_pages,
                new_articles=counters[ChangeType.NEW],
                updated_articles=counters[ChangeType.UPDATED],
                unchanged_articles=counters[ChangeType.UNCHANGED],
                failed_pages=failed_pages,
            )
            self._log.info(
                "crawl_target_completed",
                target_id=str(target.id),
                crawl_run_id=str(run.id),
                url=target.url,
                crawl_mode=target.crawl_mode.value,
                duration=time.perf_counter() - started,
                visited_pages=monitoring_result.visited_pages,
                new_articles=monitoring_result.new_articles,
                updated_articles=monitoring_result.updated_articles,
                unchanged_articles=monitoring_result.unchanged_articles,
                failed_pages=monitoring_result.failed_pages,
            )
            return monitoring_result
        except Exception as error:
            await self._record_failure(target, run, error)
            self._log.error(
                "crawl_target_failed",
                target_id=str(target.id),
                crawl_run_id=str(run.id),
                url=target.url,
                crawl_mode=target.crawl_mode.value,
                duration=time.perf_counter() - started,
                error_type=type(error).__name__,
            )
            raise

    async def _record_failure(self, target: CrawlTarget, run: CrawlRun, error: Exception) -> None:
        failed_at = self._clock()
        failed_target = target.model_copy(update={"failure_count": target.failure_count + 1})
        delay = failed_target.retry_delay_seconds(
            base_seconds=self._retry_base_seconds,
            max_seconds=self._retry_max_seconds,
        )
        async with self._uow_factory() as uow:
            await uow.targets.mark_failed(
                target.id,
                failed_at=failed_at,
                error=type(error).__name__,
                next_retry_at=failed_at + timedelta(seconds=delay),
            )
            await uow.runs.save(
                run.model_copy(
                    update={
                        "status": CrawlJobStatus.FAILED,
                        "failed_pages": 1,
                        "completed_at": failed_at,
                        "error": type(error).__name__,
                    }
                )
            )
            await uow.commit()

    async def run_due_targets(
        self, *, worker_id: str, batch_size: int, lease_seconds: int
    ) -> list[MonitoringRunResult]:
        """Claim a batch once and isolate each target failure."""
        async with self._uow_factory() as uow:
            targets = await uow.targets.claim_due(
                now=self._clock(),
                limit=batch_size,
                lease_owner=worker_id,
                lease_seconds=lease_seconds,
            )
            await uow.commit()
        results: list[MonitoringRunResult] = []
        for target in targets:
            try:
                results.append(await self._run_claimed_target(target))
            except Exception:
                continue
        return results
