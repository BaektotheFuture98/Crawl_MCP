from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from minio import Minio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from crawling_mcp.adapters.storage.minio_store import MinioObjectStore
from crawling_mcp.adapters.storage.postgres_repository import PostgresRepository
from crawling_mcp.domain.models import CrawlResult, PageItem, PageSnapshot

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
        publisher="동아일보",
        reporter="홍길동 기자",
        published_at=datetime(2026, 8, 10, 0, 30, tzinfo=UTC),
        meta_description="기사 요약",
    )
    snapshot = PageSnapshot(
        url=item.url,
        html="<html><article>기사 본문</article></html>",
        status_code=200,
    )

    await repository.start_job(job)
    await repository.save_page(job.job_id, [item], snapshot)
    await repository.save_page(job.job_id, [item], snapshot)
    await repository.complete_job(job.job_id)
    stored = await repository.get_job(job.job_id)

    assert stored is not None
    assert stored.visited_pages == 1
    assert stored.succeeded_pages == 1
    assert len(stored.items) == 1
    assert stored.items[0].title == "기사 제목"
    assert stored.items[0].publisher == "동아일보"
    assert stored.items[0].reporter == "홍길동 기자"
    assert stored.items[0].meta_description == "기사 요약"
    assert stored.items[0].published_at == item.published_at
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT a.id, o.raw_html_key FROM article AS a "
                    "JOIN crawl_article_objects AS o ON o.article_id = a.id "
                    "WHERE o.crawl_job_id = :job_id"
                ),
                {"job_id": job.job_id},
            )
        ).one()
    object_info = client.stat_object("crawl-data", row.raw_html_key)
    assert row.id.version == 7
    assert object_info.size == len(snapshot.html.encode("utf-8"))
    await repository.close()
