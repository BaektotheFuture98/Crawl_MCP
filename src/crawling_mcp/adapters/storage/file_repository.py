from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import UUID

from crawling_mcp.adapters.storage.memory_repository import InMemoryRepository
from crawling_mcp.domain.models import CrawlFailure, CrawlResult, PageItem


class FileRepository(InMemoryRepository):
    """JSON file repository using atomic replacement."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root
        self._file_lock = asyncio.Lock()

    async def _persist(self, job_id: UUID) -> None:
        async with self._file_lock:
            job = await super().get_job(job_id)
            if job is None:
                return
            await asyncio.to_thread(self._write_atomic, job)

    def _write_atomic(self, job: CrawlResult) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._root / f"{job.job_id}.json"
        temporary = self._root / f".{job.job_id}.tmp"
        temporary.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, target)

    async def start_job(self, result: CrawlResult) -> None:
        """Create and persist a job record."""
        await super().start_job(result)
        await self._persist(result.job_id)

    async def save_page(self, job_id: UUID, item: PageItem) -> None:
        """Append and persist a successful page."""
        await super().save_page(job_id, item)
        await self._persist(job_id)

    async def save_failure(self, job_id: UUID, failure: CrawlFailure) -> None:
        """Append and persist a failed page."""
        await super().save_failure(job_id, failure)
        await self._persist(job_id)

    async def set_counts(
        self,
        job_id: UUID,
        *,
        visited_pages: int,
        succeeded_pages: int,
        failed_pages: int,
    ) -> None:
        """Set and persist page-level outcome counts."""
        await super().set_counts(
            job_id,
            visited_pages=visited_pages,
            succeeded_pages=succeeded_pages,
            failed_pages=failed_pages,
        )
        await self._persist(job_id)

    async def complete_job(self, job_id: UUID) -> None:
        """Complete and persist a job."""
        await super().complete_job(job_id)
        await self._persist(job_id)

    async def get_job(self, job_id: UUID) -> CrawlResult | None:
        """Return a cached job or load it from disk."""
        cached = await super().get_job(job_id)
        if cached is not None:
            return cached
        path = self._root / f"{job_id}.json"
        if not await asyncio.to_thread(path.is_file):
            return None
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        loaded = CrawlResult.model_validate_json(text)
        await super().start_job(loaded)
        return loaded.model_copy(deep=True)
