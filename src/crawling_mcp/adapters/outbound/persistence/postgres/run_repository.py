from __future__ import annotations

import builtins
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from crawling_mcp.adapters.outbound.persistence.postgres.mapping import run_from_row
from crawling_mcp.adapters.outbound.persistence.postgres.schema import crawl_run
from crawling_mcp.domain.enums import CrawlJobStatus
from crawling_mcp.domain.monitoring import CrawlRun, CrawlRunCreate


class PostgresCrawlRunRepository:
    """Async adapter for compact Worker execution records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: CrawlRunCreate) -> CrawlRun:
        row = (
            (
                await self._session.execute(
                    sa.insert(crawl_run)
                    .values(
                        target_id=run.target_id, status=run.status.value, started_at=run.started_at
                    )
                    .returning(crawl_run)
                )
            )
            .mappings()
            .one()
        )
        return run_from_row(row)

    async def save(self, run: CrawlRun) -> CrawlRun:
        row = (
            (
                await self._session.execute(
                    sa.update(crawl_run)
                    .where(crawl_run.c.id == run.id)
                    .values(
                        status=run.status.value,
                        visited_pages=run.visited_pages,
                        discovered_articles=run.discovered_articles,
                        inserted_articles=run.inserted_articles,
                        duplicate_articles=run.duplicate_articles,
                        failed_pages=run.failed_pages,
                        completed_at=run.completed_at,
                        error=run.error,
                    )
                    .returning(crawl_run)
                )
            )
            .mappings()
            .one()
        )
        return run_from_row(row)

    async def save_terminal(self, run: CrawlRun) -> bool:
        updated = await self._session.execute(
            sa.update(crawl_run)
            .where(
                crawl_run.c.id == run.id,
                crawl_run.c.status == CrawlJobStatus.RUNNING.value,
            )
            .values(
                status=run.status.value,
                visited_pages=run.visited_pages,
                discovered_articles=run.discovered_articles,
                inserted_articles=run.inserted_articles,
                duplicate_articles=run.duplicate_articles,
                failed_pages=run.failed_pages,
                completed_at=run.completed_at,
                error=run.error,
            )
            .returning(crawl_run.c.id)
        )
        return updated.scalar_one_or_none() is not None

    async def fail_running(self, target_id: UUID, *, completed_at: datetime, error: str) -> int:
        updated = await self._session.execute(
            sa.update(crawl_run)
            .where(
                crawl_run.c.target_id == target_id,
                crawl_run.c.status == CrawlJobStatus.RUNNING.value,
            )
            .values(
                status=CrawlJobStatus.FAILED.value,
                completed_at=completed_at,
                error=error,
            )
            .returning(crawl_run.c.id)
        )
        return len(updated.scalars().all())

    async def latest(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> builtins.list[CrawlRun]:
        statement = sa.select(crawl_run).order_by(crawl_run.c.started_at.desc()).limit(limit)
        if target_id is not None:
            statement = statement.where(crawl_run.c.target_id == target_id)
        rows = (await self._session.execute(statement)).mappings().all()
        return [run_from_row(row) for row in rows]
