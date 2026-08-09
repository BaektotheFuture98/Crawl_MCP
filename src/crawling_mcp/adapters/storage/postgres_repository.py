from __future__ import annotations

import contextlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from crawling_mcp.domain.enums import ErrorCode
from crawling_mcp.domain.models import CrawlFailure, CrawlResult, PageItem
from crawling_mcp.ports.object_store import ObjectStore, StoredObject


class PostgresRepository:
    """Persist crawl jobs and append-only article rows in PostgreSQL."""

    def __init__(self, *, engine: AsyncEngine, objects: ObjectStore) -> None:
        self._engine = engine
        self._objects = objects

    @staticmethod
    def article_values(
        job_id: UUID, item: PageItem, raw_html: StoredObject
    ) -> dict[str, Any]:
        """Map an extracted page and immutable object metadata into one article row."""
        return {
            "id": uuid4(),
            "crawl_job_id": job_id,
            "collected_at": item.collected_at,
            "published_at": item.published_at,
            "title": item.title,
            "content": item.content,
            "source": item.source,
            "url": item.url,
            "canonical_url": item.canonical_url,
            "http_status_code": item.http_status_code,
            "language": item.language,
            "metadata": item.metadata,
            "raw_html_key": raw_html.key,
            "raw_html_uri": raw_html.uri,
            "raw_html_sha256": raw_html.sha256,
            "raw_html_size_bytes": raw_html.size_bytes,
        }

    async def start_job(self, result: CrawlResult) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO crawl_jobs (
                        id, start_url, visited_pages, succeeded_pages, failed_pages, started_at
                    ) VALUES (
                        :id, :start_url, :visited_pages, :succeeded_pages, :failed_pages,
                        :started_at
                    )
                    """
                ),
                {
                    "id": result.job_id,
                    "start_url": result.start_url,
                    "visited_pages": result.visited_pages,
                    "succeeded_pages": result.succeeded_pages,
                    "failed_pages": result.failed_pages,
                    "started_at": result.started_at,
                },
            )

    async def save_page(self, job_id: UUID, item: PageItem) -> None:
        if item.raw_html is None:
            raise ValueError("raw_html is required when persisting an article")
        raw_html = await self._objects.put_html(job_id, item.url, item.raw_html)
        values = self.article_values(job_id, item, raw_html)
        try:
            async with self._engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO articles (
                            id, crawl_job_id, collected_at, published_at, title, content, source,
                            url,
                            canonical_url, http_status_code, language, metadata, raw_html_key,
                            raw_html_uri, raw_html_sha256, raw_html_size_bytes
                        ) VALUES (
                            :id, :crawl_job_id, :collected_at, :published_at, :title, :content,
                            :source,
                            :url, :canonical_url, :http_status_code, :language,
                            CAST(:metadata AS jsonb), :raw_html_key, :raw_html_uri,
                            :raw_html_sha256, :raw_html_size_bytes
                        )
                        """
                    ),
                    {**values, "metadata": json.dumps(values["metadata"], ensure_ascii=False)},
                )
                await connection.execute(
                    text(
                        """
                        UPDATE crawl_jobs
                        SET visited_pages = visited_pages + 1, succeeded_pages = succeeded_pages + 1
                        WHERE id = :job_id
                        """
                    ),
                    {"job_id": job_id},
                )
        except Exception:
            with contextlib.suppress(Exception):
                await self._objects.delete(raw_html.key)
            raise

    async def save_failure(self, job_id: UUID, failure: CrawlFailure) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO crawl_failures (
                        id, crawl_job_id, url, error_code, message, details, artifacts
                    )
                    VALUES (
                        :id, :crawl_job_id, :url, :error_code, :message,
                        CAST(:details AS jsonb), CAST(:artifacts AS jsonb)
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "crawl_job_id": job_id,
                    "url": failure.url,
                    "error_code": failure.error_code.value,
                    "message": failure.message,
                    "details": json.dumps(failure.details, ensure_ascii=False),
                    "artifacts": json.dumps(failure.artifacts, ensure_ascii=False),
                },
            )
            await connection.execute(
                text(
                    """
                    UPDATE crawl_jobs
                    SET visited_pages = visited_pages + 1, failed_pages = failed_pages + 1
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job_id},
            )

    async def set_counts(
        self,
        job_id: UUID,
        *,
        visited_pages: int,
        succeeded_pages: int,
        failed_pages: int,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE crawl_jobs
                    SET visited_pages = :visited_pages,
                        succeeded_pages = :succeeded_pages,
                        failed_pages = :failed_pages
                    WHERE id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "visited_pages": visited_pages,
                    "succeeded_pages": succeeded_pages,
                    "failed_pages": failed_pages,
                },
            )

    async def complete_job(self, job_id: UUID) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text("UPDATE crawl_jobs SET completed_at = CURRENT_TIMESTAMP WHERE id = :job_id"),
                {"job_id": job_id},
            )

    async def get_job(self, job_id: UUID) -> CrawlResult | None:
        async with self._engine.connect() as connection:
            job = (
                await connection.execute(
                    text("SELECT * FROM crawl_jobs WHERE id = :job_id"), {"job_id": job_id}
                )
            ).mappings().one_or_none()
            if job is None:
                return None
            article_rows = (
                await connection.execute(
                    text(
                        "SELECT * FROM articles WHERE crawl_job_id = :job_id "
                        "ORDER BY collected_at, id"
                    ),
                    {"job_id": job_id},
                )
            ).mappings().all()
            failure_rows = (
                await connection.execute(
                    text(
                        "SELECT * FROM crawl_failures WHERE crawl_job_id = :job_id "
                        "ORDER BY created_at, id"
                    ),
                    {"job_id": job_id},
                )
            ).mappings().all()
        items = [
            PageItem(
                url=str(row["url"]),
                title=str(row["title"]),
                content=str(row["content"]),
                metadata=dict(row["metadata"]),
                canonical_url=row["canonical_url"],
                language=row["language"],
                http_status_code=row["http_status_code"],
                published_at=row["published_at"],
                source=row["source"],
                collected_at=row["collected_at"],
            )
            for row in article_rows
        ]
        failures = [
            CrawlFailure(
                url=str(row["url"]),
                error_code=ErrorCode(str(row["error_code"])),
                message=str(row["message"]),
                details=dict(row["details"]),
                artifacts=dict(row["artifacts"]),
            )
            for row in failure_rows
        ]
        return CrawlResult(
            job_id=job["id"],
            start_url=str(job["start_url"]),
            visited_pages=int(job["visited_pages"]),
            succeeded_pages=int(job["succeeded_pages"]),
            failed_pages=int(job["failed_pages"]),
            items=items,
            failures=failures,
            started_at=job["started_at"],
            completed_at=job["completed_at"],
        )

    async def close(self) -> None:
        await self._engine.dispose()
