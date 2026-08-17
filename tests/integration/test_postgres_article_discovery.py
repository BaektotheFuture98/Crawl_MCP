from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from crawling_mcp.adapters.outbound.extraction.articles import ArticleExtractorRegistry
from crawling_mcp.adapters.outbound.persistence.postgres import PostgresMonitoringStore
from crawling_mcp.application.article_collection_service import ArticleCollectionService
from crawling_mcp.domain.articles import ArticleCandidate
from crawling_mcp.domain.models import CrawlExecution, CrawlRequest, CrawlResult, PageSnapshot
from crawling_mcp.domain.monitoring import CrawlTargetCreate

_DSN = "postgresql+asyncpg://crawler:crawler@127.0.0.1:54329/crawling"


def require_storage_test() -> None:
    if os.getenv("CRAWLING_MCP_RUN_STORAGE_INTEGRATION") != "1":
        pytest.skip("set CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1")


async def clean(engine: object) -> None:
    async with engine.begin() as connection:  # type: ignore[union-attr]
        await connection.execute(
            sa.text("TRUNCATE article_discovery, crawl_run, crawl_target, article CASCADE")
        )


async def run_alembic(*arguments: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "alembic",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (stdout + stderr).decode()


class Extractor:
    name = "integration"

    def __init__(self, candidate: ArticleCandidate) -> None:
        self.candidate = candidate

    async def extract_articles(self, snapshot: PageSnapshot) -> list[ArticleCandidate]:
        del snapshot
        return [self.candidate]


class Runner:
    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        assert execution is not None and execution.page_handler is not None
        await execution.page_handler(PageSnapshot(url=request.start_url, html="<html></html>"), [])
        return CrawlResult(
            job_id=execution.job_id,
            start_url=request.start_url,
            visited_pages=1,
            succeeded_pages=1,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_collection_is_idempotent_and_does_not_apply_article_edits() -> None:
    require_storage_test()
    engine = create_async_engine(_DSN)
    store = PostgresMonitoringStore(engine)
    now = datetime(2026, 8, 17, 3, 0, tzinfo=UTC)
    try:
        await clean(engine)
        async with store() as uow:
            target = await uow.targets.create(
                CrawlTargetCreate(
                    url="https://example.com/feed",
                    interval_seconds=60,
                    discovery_lag_seconds=0,
                    discovery_overlap_seconds=300,
                )
            )
            target = await uow.targets.save(
                target.model_copy(
                    update={
                        "discovery_watermark_at": now - timedelta(minutes=10),
                        "updated_at": now - timedelta(minutes=10),
                    }
                )
            )
            await uow.commit()
        original = ArticleCandidate(
            url="https://example.com/article?utm_source=test",
            title="기사 제목",
            content="원문",
            published_at=now - timedelta(minutes=1),
        )
        first_service = ArticleCollectionService(
            crawler=Runner(),
            article_extractors=ArticleExtractorRegistry(default=Extractor(original)),
            uow_factory=store,
            clock=lambda: now,
        )
        first = await first_service.run_target(target.id, force=True)
        second_service = ArticleCollectionService(
            crawler=Runner(),
            article_extractors=ArticleExtractorRegistry(
                default=Extractor(original.model_copy(update={"content": "수정본"}))
            ),
            uow_factory=store,
            clock=lambda: now + timedelta(minutes=1),
        )
        second = await second_service.run_target(target.id, force=True)

        assert first is not None and first.inserted_articles == 1
        assert second is not None and second.duplicate_articles == 1
        async with engine.connect() as connection:
            article_row = (
                await connection.execute(sa.text("SELECT id, url, ar_content FROM article"))
            ).one()
            discovery_count = await connection.scalar(
                sa.text("SELECT count(*) FROM article_discovery")
            )
        assert article_row.id.version == 7
        assert article_row.url == "https://example.com/article"
        assert article_row.ar_content == "원문"
        assert discovery_count == 1
    finally:
        await store.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_article_discovery_migration_preserves_relationship_run_and_watermark() -> None:
    require_storage_test()
    engine = create_async_engine(_DSN)
    try:
        await clean(engine)
    finally:
        await engine.dispose()
    await run_alembic("downgrade", "20260817_02")
    try:
        observed_at = datetime(2026, 8, 17, 2, 0, tzinfo=UTC)
        published_at = datetime(2026, 8, 17, 10, 30)
        engine = create_async_engine(_DSN)
        try:
            async with engine.begin() as connection:
                target_id = await connection.scalar(
                    sa.text(
                        "INSERT INTO crawl_target (url, interval_seconds, crawl_mode) "
                        "VALUES ('https://example.com/migrated', 60, 'http') RETURNING id"
                    )
                )
                article_id = await connection.scalar(
                    sa.text(
                        "INSERT INTO article (ar_title, ar_content, url, published_at) "
                        "VALUES ('기존 기사', '기존 본문', :url, :published_at) RETURNING id"
                    ),
                    {
                        "url": "https://example.com/migrated-article",
                        "published_at": published_at,
                    },
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO article_crawl_state "
                        "(article_id, target_id, url, content_hash, first_seen_at, last_seen_at) "
                        "VALUES (:article_id, :target_id, :url, :hash, :seen, :seen)"
                    ),
                    {
                        "article_id": article_id,
                        "target_id": target_id,
                        "url": "https://example.com/migrated-article",
                        "hash": "a" * 64,
                        "seen": observed_at,
                    },
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO crawl_run "
                        "(target_id, status, new_articles, updated_articles, "
                        "unchanged_articles, started_at) "
                        "VALUES (:target_id, 'completed', 2, 1, 3, :started_at)"
                    ),
                    {"target_id": target_id, "started_at": observed_at},
                )
        finally:
            await engine.dispose()

        await run_alembic("upgrade", "head")
        engine = create_async_engine(_DSN)
        try:
            async with engine.connect() as connection:
                discovery = (
                    await connection.execute(
                        sa.text(
                            "SELECT target_id, article_id, discovered_at FROM article_discovery"
                        )
                    )
                ).one()
                run = (
                    await connection.execute(
                        sa.text(
                            "SELECT discovered_articles, inserted_articles, duplicate_articles "
                            "FROM crawl_run"
                        )
                    )
                ).one()
                watermark = await connection.scalar(
                    sa.text(
                        "SELECT discovery_watermark_at FROM crawl_target WHERE id = :target_id"
                    ),
                    {"target_id": target_id},
                )
        finally:
            await engine.dispose()

        assert (discovery.target_id, discovery.article_id, discovery.discovered_at) == (
            target_id,
            article_id,
            observed_at,
        )
        assert tuple(run) == (6, 2, 4)
        assert watermark == datetime(2026, 8, 17, 1, 30, tzinfo=UTC)

        await run_alembic("downgrade", "20260817_02")
        engine = create_async_engine(_DSN)
        try:
            async with engine.connect() as connection:
                legacy = (
                    await connection.execute(
                        sa.text(
                            "SELECT target_id, article_id, url, first_seen_at, "
                            "last_seen_at, last_change_type FROM article_crawl_state"
                        )
                    )
                ).one()
                legacy_run = (
                    await connection.execute(
                        sa.text(
                            "SELECT new_articles, updated_articles, unchanged_articles "
                            "FROM crawl_run"
                        )
                    )
                ).one()
                constraints = await connection.run_sync(
                    lambda sync_connection: (
                        sa.inspect(sync_connection).get_pk_constraint("article_crawl_state"),
                        sa.inspect(sync_connection).get_unique_constraints("article_crawl_state"),
                    )
                )
        finally:
            await engine.dispose()

        assert legacy.target_id == target_id
        assert legacy.article_id == article_id
        assert legacy.url == "https://example.com/migrated-article"
        assert legacy.first_seen_at == legacy.last_seen_at == observed_at
        assert legacy.last_change_type == "NEW"
        assert tuple(legacy_run) == (2, 0, 4)
        primary_key, unique_constraints = constraints
        assert primary_key["constrained_columns"] == ["target_id", "article_id"]
        assert any(
            constraint["column_names"] == ["target_id", "url"] for constraint in unique_constraints
        )
    finally:
        await run_alembic("upgrade", "head")
