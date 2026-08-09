from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from crawling_mcp.domain.enums import ErrorCode
from crawling_mcp.domain.models import CrawlFailure, CrawlResult, PageItem, PageSnapshot
from crawling_mcp.ports.object_store import ObjectStore, StoredObject


class PostgresRepository:
    """Persist crawl jobs and append-only article rows in PostgreSQL."""

    def __init__(self, *, engine: AsyncEngine, objects: ObjectStore) -> None:
        self._engine = engine
        self._objects = objects

    @staticmethod
    def article_values(item: PageItem) -> dict[str, Any]:
        """Map an extracted page into the public ARTICLE table contract."""
        return {
            "ar_title": item.title,
            "ar_content": item.content,
            "reporter": item.reporter[:100] if item.reporter else None,
            "publisher": item.publisher[:100] if item.publisher else None,
            "url": item.url,
            "published_at": PostgresRepository._to_storage_timestamp(item.published_at),
        }

    @staticmethod
    def article_object_values(
        job_id: UUID,
        article_id: UUID,
        item: PageItem,
        raw_html: StoredObject,
    ) -> dict[str, Any]:
        """Map crawl-only metadata into the sidecar object-reference table."""
        return {
            "article_id": article_id,
            "crawl_job_id": job_id,
            "collected_at": item.collected_at,
            "meta_description": item.meta_description,
            "canonical_url": item.canonical_url,
            "http_status_code": item.http_status_code,
            "language": item.language,
            "metadata": item.metadata,
            "raw_html_key": raw_html.key,
            "raw_html_uri": raw_html.uri,
            "raw_html_sha256": raw_html.sha256,
            "raw_html_size_bytes": raw_html.size_bytes,
        }

    @staticmethod
    def _to_storage_timestamp(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)

    @staticmethod
    def _from_storage_timestamp(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo("Asia/Seoul"))
        return value.astimezone(UTC)

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

    async def save_page(self, job_id: UUID, items: list[PageItem], snapshot: PageSnapshot) -> None:
        upload = asyncio.create_task(self._objects.put_html(job_id, snapshot.url, snapshot.html))
        try:
            raw_html = await asyncio.shield(upload)
        except asyncio.CancelledError:
            try:
                raw_html = await upload
            except BaseException:
                raise
            with contextlib.suppress(Exception):
                await asyncio.shield(self._objects.delete(raw_html.key))
            raise

        page_key = hashlib.sha256(snapshot.url.encode("utf-8")).hexdigest()

        async def persist() -> bool:
            async with self._engine.begin() as connection:
                claimed = (
                    await connection.execute(
                        text(
                            """
                            INSERT INTO crawl_page_commits (crawl_job_id, page_key)
                            VALUES (:job_id, :page_key)
                            ON CONFLICT (crawl_job_id, page_key) DO NOTHING
                            RETURNING page_key
                            """
                        ),
                        {"job_id": job_id, "page_key": page_key},
                    )
                ).scalar_one_or_none()
                if claimed is None:
                    return False
                for item in items:
                    article_id = (
                        await connection.execute(
                            text(
                                """
                                INSERT INTO article (
                                    ar_title, ar_content, reporter, publisher, url, published_at
                                ) VALUES (
                                    :ar_title, :ar_content, :reporter, :publisher, :url,
                                    :published_at
                                )
                                RETURNING id
                                """
                            ),
                            self.article_values(item),
                        )
                    ).scalar_one()
                    object_values = self.article_object_values(job_id, article_id, item, raw_html)
                    await connection.execute(
                        text(
                            """
                            INSERT INTO crawl_article_objects (
                                article_id, crawl_job_id, collected_at, canonical_url,
                                meta_description, http_status_code, language, metadata,
                                raw_html_key, raw_html_uri, raw_html_sha256,
                                raw_html_size_bytes
                            ) VALUES (
                                :article_id, :crawl_job_id, :collected_at, :canonical_url,
                                :meta_description, :http_status_code, :language,
                                CAST(:metadata AS jsonb),
                                :raw_html_key, :raw_html_uri, :raw_html_sha256,
                                :raw_html_size_bytes
                            )
                            """
                        ),
                        {
                            **object_values,
                            "metadata": json.dumps(object_values["metadata"], ensure_ascii=False),
                        },
                    )
                await connection.execute(
                    text(
                        """
                        UPDATE crawl_jobs
                        SET visited_pages = visited_pages + 1,
                            succeeded_pages = succeeded_pages + 1
                        WHERE id = :job_id
                        """
                    ),
                    {"job_id": job_id},
                )
                return True

        write = asyncio.create_task(persist())
        try:
            committed = await asyncio.shield(write)
        except asyncio.CancelledError:
            try:
                committed = await write
            except BaseException:
                with contextlib.suppress(Exception):
                    await asyncio.shield(self._objects.delete(raw_html.key))
            else:
                if not committed:
                    with contextlib.suppress(Exception):
                        await asyncio.shield(self._objects.delete(raw_html.key))
            raise
        except Exception:
            with contextlib.suppress(Exception):
                await self._objects.delete(raw_html.key)
            raise
        if not committed:
            with contextlib.suppress(Exception):
                await self._objects.delete(raw_html.key)

    async def save_failure(
        self, job_id: UUID, failure: CrawlFailure, *, count_page: bool = True
    ) -> None:
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
            if count_page:
                await connection.execute(
                    text(
                        """
                        UPDATE crawl_jobs
                        SET visited_pages = visited_pages + 1,
                            failed_pages = failed_pages + 1
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
                (
                    await connection.execute(
                        text("SELECT * FROM crawl_jobs WHERE id = :job_id"), {"job_id": job_id}
                    )
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                return None
            article_rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT a.*, o.collected_at, o.meta_description, o.canonical_url,
                                   o.http_status_code, o.language, o.metadata
                            FROM article AS a
                            JOIN crawl_article_objects AS o ON o.article_id = a.id
                            WHERE o.crawl_job_id = :job_id
                            ORDER BY o.collected_at, a.id
                            """
                        ),
                        {"job_id": job_id},
                    )
                )
                .mappings()
                .all()
            )
            failure_rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT * FROM crawl_failures WHERE crawl_job_id = :job_id "
                            "ORDER BY created_at, id"
                        ),
                        {"job_id": job_id},
                    )
                )
                .mappings()
                .all()
            )
        items = [
            PageItem(
                url=str(row["url"]),
                title=str(row["ar_title"]),
                content=str(row["ar_content"]),
                metadata=dict(row["metadata"]),
                meta_description=row["meta_description"],
                canonical_url=row["canonical_url"],
                language=row["language"],
                http_status_code=row["http_status_code"],
                published_at=self._from_storage_timestamp(row["published_at"]),
                reporter=row["reporter"],
                publisher=row["publisher"],
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
