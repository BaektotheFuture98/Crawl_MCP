from __future__ import annotations

import asyncio
from uuid import UUID

from crawling_mcp.domain.models import CrawlFailure, CrawlResult, PageItem, PageSnapshot, utc_now


class InMemoryRepository:
    """Concurrency-safe in-memory crawl repository."""

    def __init__(self) -> None:
        self._jobs: dict[UUID, CrawlResult] = {}
        self._lock = asyncio.Lock()

    async def start_job(self, result: CrawlResult) -> None:
        """Create a job record."""
        async with self._lock:
            self._jobs[result.job_id] = result.model_copy(deep=True)

    async def save_page(self, job_id: UUID, items: list[PageItem], snapshot: PageSnapshot) -> None:
        """Append every item extracted from one successful page."""
        async with self._lock:
            job = self._jobs[job_id]
            job.items.extend(item.model_copy(deep=True) for item in items)
            job.succeeded_pages += 1
            job.visited_pages += 1

    async def save_failure(
        self, job_id: UUID, failure: CrawlFailure, *, count_page: bool = True
    ) -> None:
        """Append a failed page."""
        async with self._lock:
            job = self._jobs[job_id]
            job.failures.append(failure.model_copy(deep=True))
            if count_page:
                job.failed_pages += 1
                job.visited_pages += 1

    async def set_counts(
        self,
        job_id: UUID,
        *,
        visited_pages: int,
        succeeded_pages: int,
        failed_pages: int,
    ) -> None:
        """Set page outcome counts independently from extracted item cardinality."""
        async with self._lock:
            job = self._jobs[job_id]
            job.visited_pages = visited_pages
            job.succeeded_pages = succeeded_pages
            job.failed_pages = failed_pages

    async def complete_job(self, job_id: UUID) -> None:
        """Mark a job completed."""
        async with self._lock:
            self._jobs[job_id].completed_at = utc_now()

    async def get_job(self, job_id: UUID) -> CrawlResult | None:
        """Return an isolated job copy."""
        async with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job is not None else None

    async def close(self) -> None:
        """Release repository resources."""
