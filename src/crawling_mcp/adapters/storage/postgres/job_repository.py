from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from crawling_mcp.adapters.storage.postgres.mapping import job_from_row
from crawling_mcp.adapters.storage.postgres.schema import crawl_jobs
from crawling_mcp.domain.monitoring import CrawlJobSummary


class PostgresMonitoringJobRepository:
    """SQLAlchemy async adapter for compact target-run status."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, job: CrawlJobSummary) -> None:
        await self._session.execute(
            sa.update(crawl_jobs)
            .where(crawl_jobs.c.id == job.job_id)
            .values(
                target_id=job.target_id,
                status=job.status.value,
                visited_pages=job.checked,
                failed_pages=job.failed,
                changed_pages=job.changed,
                new_pages=job.new,
                updated_pages=job.updated,
                unchanged_pages=job.unchanged,
                completed_at=job.completed_at,
                error=job.error,
            )
        )

    async def latest(self, target_id: UUID) -> CrawlJobSummary | None:
        statement = (
            sa.select(crawl_jobs)
            .where(crawl_jobs.c.target_id == target_id)
            .order_by(crawl_jobs.c.started_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return job_from_row(row) if row is not None else None
