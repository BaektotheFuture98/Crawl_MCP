from datetime import UTC, datetime

import pytest

from crawling_mcp.adapters.storage.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.application.article_persistence_service import ArticlePersistenceService
from crawling_mcp.domain.articles import ArticleCandidate, ArticleObservation
from crawling_mcp.domain.enums import ChangeType
from crawling_mcp.domain.monitoring import CrawlTargetCreate


@pytest.mark.asyncio
async def test_new_unchanged_updated_keep_one_latest_article() -> None:
    store = InMemoryMonitoringStore()
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/news", interval_seconds=60)
        )
    service = ArticlePersistenceService(uow_factory=store)
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    first = ArticleCandidate(url="https://example.com/a", title="제목", content="본문")

    new = await service.persist(
        target_id=target.id,
        observation=ArticleObservation(candidate=first, etag='"v1"'),
        observed_at=now,
    )
    unchanged = await service.persist(
        target_id=target.id,
        observation=ArticleObservation(candidate=first, etag='"v1"'),
        observed_at=now,
    )
    updated = await service.persist(
        target_id=target.id,
        observation=ArticleObservation(
            candidate=first.model_copy(update={"content": "수정 본문"}), etag='"v2"'
        ),
        observed_at=now,
    )

    assert [new.change_type, unchanged.change_type, updated.change_type] == [
        ChangeType.NEW,
        ChangeType.UNCHANGED,
        ChangeType.UPDATED,
    ]
    assert new.article_id == unchanged.article_id == updated.article_id
    async with store() as uow:
        article = await uow.articles.get_by_id(new.article_id)
        state = await uow.states.find_by_url(target.id, first.url)
    assert article is not None and article.content == "수정 본문"
    assert state is not None and state.last_change_type is ChangeType.UPDATED
    assert state.etag == '"v2"'


@pytest.mark.asyncio
async def test_existing_article_without_state_is_new_for_target_but_not_reinserted() -> None:
    store = InMemoryMonitoringStore()
    candidate = ArticleCandidate(url="https://example.com/a", title="제목", content="본문")
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com", interval_seconds=60)
        )
        existing = await uow.articles.insert_or_get(candidate)
    result = await ArticlePersistenceService(uow_factory=store).persist(
        target_id=target.id,
        observation=ArticleObservation(candidate=candidate),
        observed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert result.article_id == existing.id
    assert result.change_type is ChangeType.NEW


@pytest.mark.asyncio
async def test_overlapping_targets_keep_independent_state_for_shared_article() -> None:
    store = InMemoryMonitoringStore()
    async with store() as uow:
        first_target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/feed-a", interval_seconds=60)
        )
        second_target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/feed-b", interval_seconds=60)
        )
    service = ArticlePersistenceService(uow_factory=store)
    observed_at = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    candidate = ArticleCandidate(
        url="https://example.com/shared",
        title="공유 기사",
        content="본문",
    )

    first = await service.persist(
        target_id=first_target.id,
        observation=ArticleObservation(candidate=candidate, etag='"feed-a"'),
        observed_at=observed_at,
    )
    second = await service.persist(
        target_id=second_target.id,
        observation=ArticleObservation(candidate=candidate, etag='"feed-b"'),
        observed_at=observed_at,
    )

    assert first.change_type is ChangeType.NEW
    assert second.change_type is ChangeType.NEW
    assert first.article_id == second.article_id
    assert len(store._articles) == 1
    async with store() as uow:
        first_state = await uow.states.find_by_url(first_target.id, candidate.url)
        second_state = await uow.states.find_by_url(second_target.id, candidate.url)
    assert first_state is not None and first_state.etag == '"feed-a"'
    assert second_state is not None and second_state.etag == '"feed-b"'
