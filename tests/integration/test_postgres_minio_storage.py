from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from minio import Minio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from crawling_mcp.adapters.storage.minio_store import MinioObjectStore
from crawling_mcp.adapters.storage.postgres_repository import PostgresRepository
from crawling_mcp.domain.models import CrawlResult, PageItem

_POSTGRES_DSN = "postgresql+asyncpg://crawler:crawler@127.0.0.1:54329/crawling"
_MINIO_ENDPOINT = "127.0.0.1:9009"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_repository_persists_article_history_and_raw_html() -> None:
    if os.getenv("CRAWLING_MCP_RUN_STORAGE_INTEGRATION") != "1":
        pytest.skip("set CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 after starting storage services")
    engine = create_async_engine(_POSTGRES_DSN)
    client = Minio(_MINIO_ENDPOINT, access_key="minioadmin", secret_key="minioadmin", secure=False)
    objects = MinioObjectStore(bucket="crawl-data", client=client)
    repository = PostgresRepository(engine=engine, objects=objects)
    job = CrawlResult(start_url="https://news.example.com/article/42")
    item = PageItem(
        url="https://news.example.com/article/42",
        title="기사 제목",
        content="기사 본문",
        source="동아일보",
        published_at=datetime(2026, 8, 10, 0, 30, tzinfo=UTC),
        raw_html="<html><article>기사 본문</article></html>",
    )

    await repository.start_job(job)
    await repository.save_page(job.job_id, item)
    await repository.complete_job(job.job_id)
    stored = await repository.get_job(job.job_id)

    assert stored is not None
    assert stored.items[0].title == "기사 제목"
    assert stored.items[0].source == "동아일보"
    assert stored.items[0].published_at == item.published_at
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT raw_html_key FROM articles WHERE crawl_job_id = :job_id"),
                {"job_id": job.job_id},
            )
        ).one()
    object_info = client.stat_object("crawl-data", row.raw_html_key)
    assert object_info.size == len(item.raw_html.encode("utf-8"))
    await repository.close()
