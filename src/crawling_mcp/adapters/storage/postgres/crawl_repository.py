from __future__ import annotations

from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from crawling_mcp.adapters.storage.postgres.mapping import (
    failure_from_row,
    page_item_from_row,
)
from crawling_mcp.adapters.storage.postgres.schema import (
    article,
    crawl_failures,
    crawl_job_pages,
    crawl_jobs,
)
from crawling_mcp.domain.change_detector import ChangeDetector
from crawling_mcp.domain.enums import CrawlJobStatus
from crawling_mcp.domain.models import CrawlFailure, CrawlResult, PageItem, utc_now


class PostgresCrawlRepository:
    """Persist crawl jobs while deduplicating extracted article versions."""

    def __init__(self, engine: AsyncEngine, *, dispose_engine: bool = True) -> None:
        self._engine = engine
        self._dispose_engine = dispose_engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._detector = ChangeDetector()

    async def start_job(self, result: CrawlResult) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                sa.insert(crawl_jobs).values(
                    id=result.job_id,
                    start_url=result.start_url,
                    status=CrawlJobStatus.RUNNING.value,
                    visited_pages=result.visited_pages,
                    succeeded_pages=result.succeeded_pages,
                    failed_pages=result.failed_pages,
                    started_at=result.started_at,
                )
            )

    async def _article_id(self, session: AsyncSession, item: PageItem) -> UUID:
        canonical = self._detector.canonicalize(item)
        statement = (
            insert(article)
            .values(
                collected_at=item.collected_at,
                published_at=item.published_at,
                title=item.title,
                content=item.content,
                source=item.source or item.publisher,
                url=canonical.url,
                content_hash=canonical.content_hash,
            )
            .on_conflict_do_update(
                constraint="uq_article_url_content_hash",
                set_={"collected_at": article.c.collected_at},
            )
            .returning(article.c.id)
        )
        return cast(UUID, (await session.execute(statement)).scalar_one())

    async def save_page(self, job_id: UUID, item: PageItem) -> None:
        async with self._sessions.begin() as session:
            article_id = await self._article_id(session, item)
            await session.execute(
                insert(crawl_job_pages)
                .values(
                    crawl_job_id=job_id,
                    article_id=article_id,
                    url=item.url,
                    metadata=item.metadata,
                    collected_at=item.collected_at,
                )
                .on_conflict_do_nothing()
            )

    async def save_failure(self, job_id: UUID, failure: CrawlFailure) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                sa.insert(crawl_failures).values(
                    crawl_job_id=job_id,
                    url=failure.url,
                    error_code=failure.error_code.value,
                    message=failure.message,
                    details=failure.details,
                    artifacts=failure.artifacts,
                )
            )

    async def set_counts(
        self,
        job_id: UUID,
        *,
        visited_pages: int,
        succeeded_pages: int,
        failed_pages: int,
    ) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                sa.update(crawl_jobs)
                .where(crawl_jobs.c.id == job_id)
                .values(
                    visited_pages=visited_pages,
                    succeeded_pages=succeeded_pages,
                    failed_pages=failed_pages,
                )
            )

    async def complete_job(self, job_id: UUID) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                sa.update(crawl_jobs)
                .where(crawl_jobs.c.id == job_id)
                .values(status=CrawlJobStatus.COMPLETED.value, completed_at=utc_now())
            )

    async def get_job(self, job_id: UUID) -> CrawlResult | None:
        async with self._sessions() as session:
            job = (
                (await session.execute(sa.select(crawl_jobs).where(crawl_jobs.c.id == job_id)))
                .mappings()
                .one_or_none()
            )
            if job is None:
                return None
            pages = (
                (
                    await session.execute(
                        sa.select(
                            article,
                            crawl_job_pages.c.metadata,
                            crawl_job_pages.c.collected_at,
                        )
                        .join(crawl_job_pages, crawl_job_pages.c.article_id == article.c.id)
                        .where(crawl_job_pages.c.crawl_job_id == job_id)
                        .order_by(crawl_job_pages.c.collected_at, article.c.id)
                    )
                )
                .mappings()
                .all()
            )
            failures = (
                (
                    await session.execute(
                        sa.select(crawl_failures)
                        .where(crawl_failures.c.crawl_job_id == job_id)
                        .order_by(crawl_failures.c.created_at, crawl_failures.c.id)
                    )
                )
                .mappings()
                .all()
            )
        return CrawlResult(
            job_id=job["id"],
            start_url=str(job["start_url"]),
            visited_pages=int(job["visited_pages"]),
            succeeded_pages=int(job["succeeded_pages"]),
            failed_pages=int(job["failed_pages"]),
            items=[page_item_from_row(row) for row in pages],
            failures=[failure_from_row(row) for row in failures],
            started_at=job["started_at"],
            completed_at=job["completed_at"],
        )

    async def close(self) -> None:
        if self._dispose_engine:
            await self._engine.dispose()
