from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from crawling_mcp.domain.enums import CrawlMode
from crawling_mcp.domain.monitoring import CollectionResult, CrawlTarget


def target(**updates: object) -> CrawlTarget:
    values: dict[str, object] = {
        "id": uuid4(),
        "url": "https://example.com",
        "interval_seconds": 300,
    }
    values.update(updates)
    return CrawlTarget.model_validate(values)


def test_enabled_target_is_due_at_next_crawl_time() -> None:
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)

    assert target(next_crawl_at=now).is_due(now)
    assert not target(next_crawl_at=now + timedelta(seconds=1)).is_due(now)
    assert not target(enabled=False, next_crawl_at=now).is_due(now)


def test_active_lease_prevents_due_target() -> None:
    now = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)

    assert not target(next_crawl_at=now, lease_expires_at=now + timedelta(seconds=30)).is_due(now)
    assert target(next_crawl_at=now, lease_expires_at=now).is_due(now)


def test_target_builds_existing_bounded_crawl_request() -> None:
    request = target(
        crawl_mode=CrawlMode.HTTP,
        auth_profile="reader",
        max_pages=7,
        max_depth=1,
    ).to_crawl_request()

    assert request.start_url == "https://example.com"
    assert request.crawl_mode is CrawlMode.HTTP
    assert request.auth_profile == "reader"
    assert request.max_pages == 7
    assert request.max_depth == 1


def test_exponential_retry_delay_is_capped() -> None:
    crawl_target = target(failure_count=8)

    assert crawl_target.retry_delay_seconds(base_seconds=30, max_seconds=3600) == 3600
    assert target(failure_count=1).retry_delay_seconds(base_seconds=30, max_seconds=3600) == 30


def test_collection_result_enforces_discovery_counter_invariant() -> None:
    result = CollectionResult(
        target_id=uuid4(),
        crawl_run_id=uuid4(),
        discovered_articles=3,
        inserted_articles=1,
        duplicate_articles=2,
    )

    assert result.discovered_articles == result.inserted_articles + result.duplicate_articles

    with pytest.raises(ValidationError):
        CollectionResult(
            target_id=uuid4(),
            crawl_run_id=uuid4(),
            discovered_articles=3,
            inserted_articles=1,
            duplicate_articles=1,
        )
