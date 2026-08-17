from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from crawling_mcp.adapters.storage.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.domain.articles import (
    ArticleCandidate,
    ArticleCrawlState,
    ArticleCrawlStateCreate,
)
from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus
from crawling_mcp.domain.monitoring import CrawlRunCreate, CrawlTargetCreate


@pytest.mark.asyncio
async def test_target_crud_due_claim_and_manual_lease() -> None:
    store = InMemoryMonitoringStore()
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    async with store() as uow:
        due = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/due", interval_seconds=60)
        )
        await uow.targets.create(
            CrawlTargetCreate(
                url="https://example.com/disabled", interval_seconds=60, enabled=False
            )
        )
        claimed = await uow.targets.claim_due(
            now=now, limit=10, lease_owner="worker-1", lease_seconds=30
        )
    assert [item.id for item in claimed] == [due.id]

    async with store() as uow:
        assert (
            await uow.targets.claim(
                due.id,
                now=now,
                lease_owner="manual",
                lease_seconds=30,
                force=True,
            )
            is None
        )
        reclaimed = await uow.targets.claim(
            due.id,
            now=now + timedelta(seconds=30),
            lease_owner="manual",
            lease_seconds=30,
            force=True,
        )
    assert reclaimed is not None and reclaimed.lease_owner == "manual"


@pytest.mark.asyncio
async def test_stale_lease_owner_cannot_renew_or_finalize_target() -> None:
    store = InMemoryMonitoringStore()
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com/leased", interval_seconds=60)
        )
        first = await uow.targets.claim(
            target.id,
            now=now,
            lease_owner="worker-a",
            lease_seconds=30,
            force=True,
        )
    assert first is not None
    expired_at = now + timedelta(seconds=31)
    async with store() as uow:
        second = await uow.targets.claim(
            target.id,
            now=expired_at,
            lease_owner="worker-b",
            lease_seconds=30,
            force=True,
        )
        assert second is not None
        assert not await uow.targets.renew_lease(
            target.id,
            lease_owner="worker-a",
            now=expired_at,
            lease_seconds=30,
        )
        assert not await uow.targets.mark_succeeded(
            target.id,
            lease_owner="worker-a",
            crawled_at=expired_at,
            next_crawl_at=expired_at + timedelta(seconds=60),
        )
        assert not await uow.targets.mark_failed(
            target.id,
            lease_owner="worker-a",
            failed_at=expired_at,
            error="stale",
            next_retry_at=expired_at + timedelta(seconds=30),
        )
        assert await uow.targets.renew_lease(
            target.id,
            lease_owner="worker-b",
            now=expired_at,
            lease_seconds=30,
        )
        assert await uow.targets.mark_succeeded(
            target.id,
            lease_owner="worker-b",
            crawled_at=expired_at,
            next_crawl_at=expired_at + timedelta(seconds=60),
        )
        stored = await uow.targets.get(target.id)
    assert stored is not None and stored.lease_owner is None


@pytest.mark.asyncio
async def test_article_crud_state_and_recent_summary_keep_body_separate() -> None:
    store = InMemoryMonitoringStore()
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com", interval_seconds=60)
        )
        article = await uow.articles.insert_or_get(
            ArticleCandidate(url="https://example.com/a", title="A", content="large body")
        )
        state = await uow.states.create(
            ArticleCrawlStateCreate(
                article_id=article.id,
                target_id=target.id,
                url=article.url,
                content_hash="a" * 64,
                first_seen_at=now,
                last_seen_at=now,
                last_changed_at=now,
                last_change_type=ChangeType.NEW,
            )
        )
        await uow.states.save(
            ArticleCrawlState.model_validate(
                state.model_dump() | {"last_seen_at": now + timedelta(seconds=1)}
            )
        )
        recent = await uow.states.recent_changes(target_id=target.id)

    assert recent[0].article_id == article.id
    assert "content" not in recent[0].model_dump()
    async with store() as uow:
        stored = await uow.articles.get_by_id(article.id)
    assert stored is not None and stored.content == "large body"


@pytest.mark.asyncio
async def test_insert_or_get_reuses_article_identity_for_one_url() -> None:
    store = InMemoryMonitoringStore()
    candidate = ArticleCandidate(url="https://example.com/a", title="A", content="body")

    async with store() as uow:
        first = await uow.articles.insert_or_get(candidate)
        second = await uow.articles.insert_or_get(
            candidate.model_copy(update={"content": "a concurrent candidate"})
        )

    assert first.id == second.id
    assert len(store._articles) == 1
    assert second.content == "body"


@pytest.mark.asyncio
async def test_crawl_run_repository_orders_latest_status() -> None:
    store = InMemoryMonitoringStore()
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com", interval_seconds=60)
        )
        first = await uow.runs.create(CrawlRunCreate(target_id=target.id, started_at=now))
        second = await uow.runs.create(
            CrawlRunCreate(target_id=target.id, started_at=now + timedelta(seconds=1))
        )
        await uow.runs.save(second.model_copy(update={"status": CrawlJobStatus.COMPLETED}))
        latest = await uow.runs.latest(target_id=target.id, limit=1)

    assert first.id != second.id
    assert latest[0].id == second.id


@pytest.mark.asyncio
async def test_stale_running_runs_are_failed_and_cannot_be_overwritten() -> None:
    store = InMemoryMonitoringStore()
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    async with store() as uow:
        target = await uow.targets.create(
            CrawlTargetCreate(url="https://example.com", interval_seconds=60)
        )
        stale = await uow.runs.create(CrawlRunCreate(target_id=target.id, started_at=now))
        reconciled = await uow.runs.fail_running(
            target.id,
            completed_at=now + timedelta(seconds=60),
            error="lease_expired",
        )
        overwritten = await uow.runs.save_terminal(
            stale.model_copy(
                update={
                    "status": CrawlJobStatus.COMPLETED,
                    "completed_at": now + timedelta(seconds=61),
                }
            )
        )
        latest = await uow.runs.latest(target_id=target.id)

    assert reconciled == 1
    assert not overwritten
    assert latest[0].status is CrawlJobStatus.FAILED
    assert latest[0].error == "lease_expired"
