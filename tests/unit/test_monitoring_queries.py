from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from crawling_mcp.adapters.storage.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.application.article_persistence_service import ArticlePersistenceService
from crawling_mcp.application.monitoring_query_service import MonitoringQueryService
from crawling_mcp.domain.articles import ArticleCandidate, ArticleObservation
from crawling_mcp.domain.enums import CrawlJobStatus, CrawlMode
from crawling_mcp.domain.monitoring import (
    ConfigureTargetRequest,
    CrawlRun,
    CrawlRunCreate,
    MonitoringRunResult,
)


class Runner:
    async def run_target(self, target_id: UUID, *, force: bool = False) -> MonitoringRunResult:
        assert force
        return MonitoringRunResult(target_id=target_id, crawl_run_id=uuid4())


@pytest.mark.asyncio
async def test_configure_target_creates_and_updates_only_supplied_fields() -> None:
    store = InMemoryMonitoringStore()
    service = MonitoringQueryService(uow_factory=store, monitoring=Runner())
    created = await service.configure_target(
        ConfigureTargetRequest(
            url="https://example.com", interval_seconds=60, crawl_mode=CrawlMode.HTTP
        )
    )

    updated = await service.configure_target(
        ConfigureTargetRequest(target_id=created.id, enabled=False, interval_seconds=120)
    )

    assert updated.url == created.url
    assert updated.crawl_mode is CrawlMode.HTTP
    assert updated.enabled is False
    assert updated.interval_seconds == 120


@pytest.mark.asyncio
async def test_article_change_summary_excludes_content_and_get_article_is_explicit() -> None:
    store = InMemoryMonitoringStore()
    service = MonitoringQueryService(uow_factory=store, monitoring=Runner())
    target = await service.configure_target(
        ConfigureTargetRequest(url="https://example.com", interval_seconds=60)
    )
    now = datetime(2026, 8, 10, tzinfo=UTC)
    persisted = await ArticlePersistenceService(uow_factory=store).persist(
        target_id=target.id,
        observation=ArticleObservation(
            candidate=ArticleCandidate(url="https://example.com/a", title="A", content="large body")
        ),
        observed_at=now,
    )
    async with store() as uow:
        run = await uow.runs.create(CrawlRunCreate(target_id=target.id, started_at=now))
        await uow.runs.save(
            CrawlRun(
                id=run.id,
                target_id=target.id,
                status=CrawlJobStatus.COMPLETED,
                visited_pages=100,
                new_articles=1,
                started_at=now,
                completed_at=now,
            )
        )

    recent = await service.get_recent_article_changes(target_id=target.id, limit=1)
    status = await service.get_crawl_status(target_id=target.id, limit=10)
    detail = await service.get_article(persisted.article_id)

    assert len(recent) == 1
    assert "content" not in recent[0].model_dump()
    assert status[0].visited_pages == 100
    assert detail is not None and detail.content == "large body"
