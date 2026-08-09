from __future__ import annotations

from typing import Protocol
from uuid import UUID

from crawling_mcp.domain.models import CrawlFailure, CrawlResult, PageItem, PageSnapshot


class CrawlRepository(Protocol):
    """Persistence port for crawl jobs and pages."""

    async def start_job(self, result: CrawlResult) -> None: ...

    async def save_page(
        self, job_id: UUID, items: list[PageItem], snapshot: PageSnapshot
    ) -> None: ...

    async def save_failure(
        self, job_id: UUID, failure: CrawlFailure, *, count_page: bool = True
    ) -> None: ...

    async def set_counts(
        self,
        job_id: UUID,
        *,
        visited_pages: int,
        succeeded_pages: int,
        failed_pages: int,
    ) -> None: ...

    async def complete_job(self, job_id: UUID) -> None: ...

    async def get_job(self, job_id: UUID) -> CrawlResult | None: ...

    async def close(self) -> None: ...
