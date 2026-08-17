from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import structlog

from crawling_mcp.application.ports.outbound.extractor import ArticleExtractorResolver
from crawling_mcp.application.ports.outbound.monitoring import (
    CrawlRunner,
    MonitoringUnitOfWorkFactory,
)
from crawling_mcp.domain.collection import ArticleDiscoveryCreate, DiscoveryWindowPolicy
from crawling_mcp.domain.enums import CrawlJobStatus
from crawling_mcp.domain.models import CrawlExecution, PageItem, PageSnapshot, utc_now
from crawling_mcp.domain.monitoring import CollectionResult, CrawlRun, CrawlRunCreate, CrawlTarget
from crawling_mcp.domain.policies import normalize_url


class LeaseLostError(RuntimeError):
    """Raised when a worker no longer owns the target it was processing."""


class ArticleCollectionService:
    """Collect newly published articles through an owner-fenced discovery window."""

    def __init__(
        self,
        *,
        crawler: CrawlRunner,
        article_extractors: ArticleExtractorResolver,
        uow_factory: MonitoringUnitOfWorkFactory,
        clock: Callable[[], datetime] = utc_now,
        window_policy: DiscoveryWindowPolicy | None = None,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 3600,
        lease_seconds: int = 600,
        heartbeat_interval_seconds: float | None = None,
    ) -> None:
        self._crawler = crawler
        self._article_extractors = article_extractors
        self._uow_factory = uow_factory
        self._clock = clock
        self._window_policy = window_policy or DiscoveryWindowPolicy()
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._lease_seconds = lease_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._log = structlog.get_logger(__name__)

    async def run_target(self, target_id: UUID, *, force: bool = False) -> CollectionResult | None:
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
        return await self._run_claimed_target(target, lease_seconds=self._lease_seconds)

    async def _run_claimed_target(
        self, target: CrawlTarget, *, lease_seconds: int
    ) -> CollectionResult:
        lease_owner = target.lease_owner
        if lease_owner is None:
            raise ValueError("claimed target must have a lease owner")
        started_at = self._clock()
        window = self._window_policy.calculate(target=target, now=started_at)
        async with self._uow_factory() as uow:
            await uow.runs.fail_running(
                target.id,
                completed_at=started_at,
                error="lease_expired",
            )
            run = await uow.runs.create(CrawlRunCreate(target_id=target.id, started_at=started_at))
            await uow.commit()

        counters = {"discovered": 0, "inserted": 0, "duplicate": 0}
        extraction_failures = 0
        processed_urls: set[str] = set()
        processed_lock = asyncio.Lock()
        counter_lock = asyncio.Lock()

        async def reserve(url: str) -> bool:
            async with processed_lock:
                if url in processed_urls:
                    return False
                processed_urls.add(url)
                return True

        async def release(url: str) -> None:
            async with processed_lock:
                processed_urls.discard(url)

        async def observe(snapshot: PageSnapshot, items: list[PageItem]) -> None:
            del items
            nonlocal extraction_failures
            domain = (urlsplit(snapshot.url).hostname or "").lower().rstrip(".")
            extractor = self._article_extractors.get(domain)
            try:
                candidates = await extractor.extract_articles(snapshot)
            except Exception as error:
                async with counter_lock:
                    extraction_failures += 1
                self._log.warning(
                    "article_extraction_failed",
                    target_id=str(target.id),
                    crawl_run_id=str(run.id),
                    url=snapshot.url,
                    extractor=extractor.name,
                    error_type=type(error).__name__,
                )
                return
            for candidate in candidates:
                if not window.contains(candidate.published_at):
                    continue
                canonical = normalize_url(candidate.url, remove_tracking=True)
                if not await reserve(canonical):
                    continue
                normalized = candidate.model_copy(update={"url": canonical})
                try:
                    async with self._uow_factory() as uow:
                        insertion = await uow.articles.insert_or_get(normalized)
                        await uow.discoveries.record(
                            ArticleDiscoveryCreate(
                                target_id=target.id,
                                article_id=insertion.article.id,
                                discovered_at=self._clock(),
                            )
                        )
                        await uow.commit()
                except Exception:
                    await release(canonical)
                    raise
                async with counter_lock:
                    counters["discovered"] += 1
                    counters["inserted" if insertion.inserted else "duplicate"] += 1

        execution = CrawlExecution(
            job_id=run.id,
            persist_result=False,
            collect_items=False,
            page_handler=observe,
        )
        timer = time.perf_counter()
        self._log.info(
            "article_collection_started",
            target_id=str(target.id),
            crawl_run_id=str(run.id),
            window_start=window.start.isoformat(),
            window_end=window.end.isoformat(),
        )
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_lease(
                target_id=target.id,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
                lease_lost=lease_lost,
            )
        )
        try:
            crawl_result = await self._crawler.crawl_site(
                target.to_crawl_request(), execution=execution
            )
            if lease_lost.is_set():
                raise LeaseLostError("target lease was lost during crawling")
            completed_at = self._clock()
            failed_pages = crawl_result.failed_pages + extraction_failures
            completed = run.model_copy(
                update={
                    "status": CrawlJobStatus.COMPLETED,
                    "visited_pages": crawl_result.visited_pages,
                    "discovered_articles": counters["discovered"],
                    "inserted_articles": counters["inserted"],
                    "duplicate_articles": counters["duplicate"],
                    "failed_pages": failed_pages,
                    "completed_at": completed_at,
                }
            )
            async with self._uow_factory() as uow:
                target_finalized = await uow.targets.mark_succeeded(
                    target.id,
                    lease_owner=lease_owner,
                    crawled_at=completed_at,
                    next_crawl_at=completed_at + timedelta(seconds=target.interval_seconds),
                    discovery_watermark_at=window.end,
                )
                if not target_finalized:
                    raise LeaseLostError("target lease was lost before completion")
                if not await uow.runs.save_terminal(completed):
                    raise LeaseLostError("crawl run was already finalized")
                await uow.commit()
            result = CollectionResult(
                target_id=target.id,
                crawl_run_id=run.id,
                visited_pages=crawl_result.visited_pages,
                discovered_articles=counters["discovered"],
                inserted_articles=counters["inserted"],
                duplicate_articles=counters["duplicate"],
                failed_pages=failed_pages,
            )
            self._log.info(
                "article_collection_completed",
                duration=time.perf_counter() - timer,
                **result.model_dump(),
            )
            return result
        except Exception as error:
            await self._record_failure(target, run, error, lease_owner=lease_owner)
            self._log.error(
                "article_collection_failed",
                target_id=str(target.id),
                crawl_run_id=str(run.id),
                duration=time.perf_counter() - timer,
                error_type=type(error).__name__,
            )
            raise
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _record_failure(
        self,
        target: CrawlTarget,
        run: CrawlRun,
        error: Exception,
        *,
        lease_owner: str,
    ) -> None:
        failed_at = self._clock()
        failed_target = target.model_copy(update={"failure_count": target.failure_count + 1})
        delay = failed_target.retry_delay_seconds(
            base_seconds=self._retry_base_seconds,
            max_seconds=self._retry_max_seconds,
        )
        async with self._uow_factory() as uow:
            target_finalized = await uow.targets.mark_failed(
                target.id,
                lease_owner=lease_owner,
                failed_at=failed_at,
                error=type(error).__name__,
                next_retry_at=failed_at + timedelta(seconds=delay),
            )
            if target_finalized:
                await uow.runs.save_terminal(
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

    async def _heartbeat_lease(
        self,
        *,
        target_id: UUID,
        lease_owner: str,
        lease_seconds: int,
        lease_lost: asyncio.Event,
    ) -> None:
        interval = self._heartbeat_interval_seconds
        if interval is None:
            interval = max(lease_seconds / 3, 0.1)
        while True:
            await asyncio.sleep(interval)
            try:
                async with self._uow_factory() as uow:
                    renewed = await uow.targets.renew_lease(
                        target_id,
                        lease_owner=lease_owner,
                        now=self._clock(),
                        lease_seconds=lease_seconds,
                    )
                    await uow.commit()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._log.error(
                    "article_collection_heartbeat_failed",
                    target_id=str(target_id),
                    lease_owner=lease_owner,
                    error_type=type(error).__name__,
                )
                lease_lost.set()
                return
            if not renewed:
                lease_lost.set()
                return

    async def run_due_targets(
        self, *, worker_id: str, batch_size: int, lease_seconds: int
    ) -> list[CollectionResult]:
        results: list[CollectionResult] = []
        for _ in range(batch_size):
            async with self._uow_factory() as uow:
                targets = await uow.targets.claim_due(
                    now=self._clock(),
                    limit=1,
                    lease_owner=worker_id,
                    lease_seconds=lease_seconds,
                )
                await uow.commit()
            if not targets:
                break
            try:
                results.append(
                    await self._run_claimed_target(targets[0], lease_seconds=lease_seconds)
                )
            except Exception:
                continue
        return results
