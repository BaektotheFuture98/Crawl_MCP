from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from crawling_mcp.adapters.outbound.persistence.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.application.collection_query_service import CollectionQueryService
from crawling_mcp.domain.articles import ArticleCandidate
from crawling_mcp.domain.collection import ArticleDiscoveryCreate
from crawling_mcp.domain.enums import CrawlJobStatus, CrawlMode
from crawling_mcp.domain.monitoring import (
    CollectionResult,
    ConfigureTargetRequest,
    CrawlRun,
    CrawlRunCreate,
)


class Runner:
    async def run_target(self, target_id: UUID, *, force: bool = False) -> CollectionResult:
        assert force
        return CollectionResult(target_id=target_id, crawl_run_id=uuid4())


@pytest.mark.asyncio
async def test_configure_target_creates_and_updates_discovery_fields() -> None:
    store = InMemoryMonitoringStore()
    service = CollectionQueryService(uow_factory=store, monitoring=Runner())
    created = await service.configure_target(
        ConfigureTargetRequest(
            url="https://example.com",
            interval_seconds=60,
            crawl_mode=CrawlMode.HTTP,
            discovery_lag_seconds=15,
        )
    )
    updated = await service.configure_target(
        ConfigureTargetRequest(
            target_id=created.id,
            enabled=False,
            interval_seconds=120,
            discovery_overlap_seconds=600,
        )
    )

    assert updated.crawl_mode is CrawlMode.HTTP
    assert updated.discovery_lag_seconds == 15
    assert updated.discovery_overlap_seconds == 600
    assert not updated.enabled


@pytest.mark.asyncio
async def test_discovery_summary_excludes_content_and_article_detail_is_explicit() -> None:
    store = InMemoryMonitoringStore()
    service = CollectionQueryService(uow_factory=store, monitoring=Runner())
    target = await service.configure_target(
        ConfigureTargetRequest(url="https://example.com", interval_seconds=60)
    )
    now = datetime(2026, 8, 10, tzinfo=UTC)
    async with store() as uow:
        insertion = await uow.articles.insert_or_get(
            ArticleCandidate(
                url="https://example.com/a",
                title="A",
                content="large body",
                published_at=now,
            )
        )
        await uow.discoveries.record(
            ArticleDiscoveryCreate(
                target_id=target.id,
                article_id=insertion.article.id,
                discovered_at=now,
            )
        )
        run = await uow.runs.create(CrawlRunCreate(target_id=target.id, started_at=now))
        await uow.runs.save(
            CrawlRun(
                id=run.id,
                target_id=target.id,
                status=CrawlJobStatus.COMPLETED,
                visited_pages=100,
                discovered_articles=1,
                inserted_articles=1,
                started_at=now,
                completed_at=now,
            )
        )

    recent = await service.get_recent_articles(target_id=target.id, limit=1)
    status = await service.get_crawl_status(target_id=target.id, limit=10)
    detail = await service.get_article(insertion.article.id)

    assert len(recent) == 1
    assert "content" not in recent[0].model_dump()
    assert status[0].inserted_articles == 1
    assert detail is not None and detail.content == "large body"
