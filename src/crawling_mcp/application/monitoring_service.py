from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import structlog

from crawling_mcp.domain.change_detector import ChangeDetector
from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus
from crawling_mcp.domain.models import (
    CrawlCacheEntry,
    CrawlExecution,
    PageItem,
    PageSnapshot,
    utc_now,
)
from crawling_mcp.domain.monitoring import (
    CrawlChangeCreate,
    CrawlJobSummary,
    CrawlSnapshotCreate,
    CrawlTarget,
    MonitoringRunResult,
)
from crawling_mcp.domain.policies import normalize_url
from crawling_mcp.ports.monitoring import CrawlRunner, MonitoringUnitOfWorkFactory


class MonitoringService:
    """Run scheduled targets through CrawlService and persist meaningful changes."""

    def __init__(
        self,
        *,
        crawler: CrawlRunner,
        uow_factory: MonitoringUnitOfWorkFactory,
        detector: ChangeDetector | None = None,
        clock: Callable[[], datetime] = utc_now,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 3600,
    ) -> None:
        self._crawler = crawler
        self._uow_factory = uow_factory
        self._detector = detector or ChangeDetector()
        self._clock = clock
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._log = structlog.get_logger(__name__)

    async def run_target(
        self, target_id: UUID, *, force: bool = False
    ) -> MonitoringRunResult | None:
        """Run one target, update versions atomically, and persist retry state on failure."""
        now = self._clock()
        async with self._uow_factory() as uow:
            target = await uow.targets.get(target_id)
            if target is None:
                raise KeyError(f"unknown crawl target: {target_id}")
            if not force and not target.is_due(now):
                return None
            previous = await uow.snapshots.latest_by_target(target.id)

        job_id = uuid4()
        observed: list[tuple[PageSnapshot, list[PageItem]]] = []
        not_modified: dict[str, PageSnapshot] = {}

        async def observe(snapshot: PageSnapshot, items: list[PageItem]) -> None:
            observed.append(
                (snapshot.model_copy(deep=True), [item.model_copy(deep=True) for item in items])
            )

        async def observe_not_modified(snapshot: PageSnapshot) -> None:
            url = normalize_url(snapshot.url, remove_tracking=True)
            not_modified[url] = snapshot.model_copy(deep=True)

        execution = CrawlExecution(
            job_id=job_id,
            cache_entries={
                url: CrawlCacheEntry(
                    url=url,
                    etag=snapshot.etag,
                    last_modified=snapshot.last_modified,
                    depth=snapshot.depth,
                )
                for url, snapshot in previous.items()
            },
            page_handler=observe,
            not_modified_handler=observe_not_modified,
        )
        started = time.perf_counter()
        self._log.info(
            "crawl_target_started",
            target_id=str(target.id),
            job_id=str(job_id),
            url=target.url,
            crawl_mode=target.crawl_mode.value,
        )
        try:
            crawl_result = await self._crawler.crawl_site(
                target.to_crawl_request(), execution=execution
            )
            counters = {"new": 0, "updated": 0, "unchanged": 0}
            async with self._uow_factory() as uow:
                for url, snapshot in not_modified.items():
                    prior = previous.get(url)
                    if prior is None:
                        continue
                    await uow.snapshots.touch(
                        prior.id,
                        seen_at=now,
                        etag=snapshot.headers.get("etag"),
                        last_modified=snapshot.headers.get("last-modified"),
                    )
                    counters["unchanged"] += 1

                processed_urls = set(not_modified)
                for page, items in observed:
                    for item in items:
                        detection = self._detector.detect(
                            previous.get(
                                normalize_url(item.canonical_url or item.url, remove_tracking=True)
                            ),
                            item,
                        )
                        url = detection.canonical.url
                        if url in processed_urls:
                            continue
                        processed_urls.add(url)
                        prior = previous.get(url)
                        if detection.change_type is ChangeType.UNCHANGED:
                            if prior is not None:
                                await uow.snapshots.touch(
                                    prior.id,
                                    seen_at=now,
                                    etag=page.headers.get("etag"),
                                    last_modified=page.headers.get("last-modified"),
                                )
                            counters["unchanged"] += 1
                            continue
                        stored = await uow.snapshots.create(
                            self._snapshot_create(target.id, page, item, detection.content_hash)
                        )
                        await uow.changes.create(
                            CrawlChangeCreate(
                                target_id=target.id,
                                change_type=detection.change_type,
                                url=stored.url,
                                title=stored.title,
                                previous_snapshot_id=prior.id if prior else None,
                                current_snapshot_id=stored.id,
                                detected_at=now,
                            )
                        )
                        key = "new" if detection.change_type is ChangeType.NEW else "updated"
                        counters[key] += 1
                        self._log.info(
                            "change_detected",
                            target_id=str(target.id),
                            job_id=str(job_id),
                            url=stored.url,
                            change_type=detection.change_type.value,
                        )

                changed = counters["new"] + counters["updated"]
                summary = CrawlJobSummary(
                    job_id=job_id,
                    target_id=target.id,
                    status=CrawlJobStatus.COMPLETED,
                    checked=crawl_result.visited_pages,
                    changed=changed,
                    new=counters["new"],
                    updated=counters["updated"],
                    unchanged=counters["unchanged"],
                    failed=crawl_result.failed_pages,
                    started_at=crawl_result.started_at,
                    completed_at=now,
                )
                await uow.jobs.save(summary)
                await uow.targets.mark_succeeded(
                    target.id,
                    crawled_at=now,
                    next_crawl_at=now + timedelta(seconds=target.interval_seconds),
                )
                await uow.commit()
            result = MonitoringRunResult(
                target_id=target.id,
                job_id=job_id,
                checked=crawl_result.visited_pages,
                changed=changed,
                new=counters["new"],
                updated=counters["updated"],
                unchanged=counters["unchanged"],
                failed=crawl_result.failed_pages,
            )
            self._log.info(
                "crawl_target_completed",
                target_id=str(target.id),
                job_id=str(job_id),
                url=target.url,
                crawl_mode=target.crawl_mode.value,
                duration=time.perf_counter() - started,
                visited_pages=result.checked,
                changed_pages=result.changed,
                failed_pages=result.failed,
            )
            return result
        except Exception as error:
            await self._record_failure(target, job_id, now, error)
            self._log.error(
                "crawl_target_failed",
                target_id=str(target.id),
                job_id=str(job_id),
                url=target.url,
                crawl_mode=target.crawl_mode.value,
                duration=time.perf_counter() - started,
                error_type=type(error).__name__,
            )
            raise

    def _snapshot_create(
        self,
        target_id: UUID,
        page: PageSnapshot,
        item: PageItem,
        content_hash: str,
    ) -> CrawlSnapshotCreate:
        canonical = self._detector.canonicalize(item)
        return CrawlSnapshotCreate(
            target_id=target_id,
            url=canonical.url,
            content_hash=content_hash,
            title=canonical.title,
            content=canonical.content,
            source=item.source or item.publisher,
            published_at=item.published_at,
            reporter=item.reporter,
            etag=page.headers.get("etag"),
            last_modified=page.headers.get("last-modified"),
            metadata=dict(item.metadata),
            depth=page.depth,
            collected_at=item.collected_at,
        )

    async def _record_failure(
        self,
        target: CrawlTarget,
        job_id: UUID,
        failed_at: datetime,
        error: Exception,
    ) -> None:
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
            await uow.jobs.save(
                CrawlJobSummary(
                    job_id=job_id,
                    target_id=target.id,
                    status=CrawlJobStatus.FAILED,
                    failed=1,
                    started_at=failed_at,
                    completed_at=failed_at,
                    error=type(error).__name__,
                )
            )
            await uow.commit()

    async def run_due_targets(
        self, *, worker_id: str, batch_size: int, lease_seconds: int
    ) -> list[MonitoringRunResult]:
        """Claim a batch and isolate target failures from the worker loop."""
        now = self._clock()
        async with self._uow_factory() as uow:
            targets = await uow.targets.claim_due(
                now=now,
                limit=batch_size,
                lease_owner=worker_id,
                lease_seconds=lease_seconds,
            )
            await uow.commit()
        results: list[MonitoringRunResult] = []
        for target in targets:
            try:
                result = await self.run_target(target.id, force=True)
            except Exception:
                continue
            if result is not None:
                results.append(result)
        return results
