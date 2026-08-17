from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from crawling_mcp.domain.collection.entities import CollectionWindow
from crawling_mcp.domain.collection.policies import DiscoveryWindowPolicy
from crawling_mcp.domain.monitoring import CrawlTarget, CrawlTargetCreate


def make_target(**updates: object) -> CrawlTarget:
    created_at = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    values: dict[str, object] = {
        "id": uuid4(),
        "url": "https://example.com/news",
        "interval_seconds": 300,
        "created_at": created_at,
        "updated_at": created_at,
    }
    values.update(updates)
    return CrawlTarget.model_validate(values)


def test_window_uses_created_at_for_first_run_with_overlap_and_lag() -> None:
    created_at = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    now = created_at + timedelta(minutes=10)
    target = make_target(
        created_at=created_at,
        discovery_overlap_seconds=120,
        discovery_lag_seconds=30,
    )

    window = DiscoveryWindowPolicy().calculate(target=target, now=now)

    assert window.start == created_at - timedelta(seconds=120)
    assert window.end == now - timedelta(seconds=30)


def test_window_uses_previous_watermark_and_clamps_inverted_window() -> None:
    watermark = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)
    target = make_target(
        discovery_watermark_at=watermark,
        discovery_overlap_seconds=60,
        discovery_lag_seconds=300,
    )

    window = DiscoveryWindowPolicy().calculate(
        target=target,
        now=watermark + timedelta(seconds=30),
    )

    assert window.start == window.end == watermark - timedelta(seconds=60)


def test_collection_window_is_start_inclusive_end_exclusive_and_rejects_naive_time() -> None:
    start = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    window = CollectionWindow(start=start, end=end)

    assert window.contains(start)
    assert not window.contains(datetime(2026, 8, 10, 1, 30))
    assert not window.contains(end)
    assert not window.contains(None)


def test_target_rejects_negative_discovery_lag_and_overlap() -> None:
    with pytest.raises(ValidationError):
        CrawlTargetCreate(
            url="https://example.com/news",
            interval_seconds=300,
            discovery_lag_seconds=-1,
        )
    with pytest.raises(ValidationError):
        CrawlTargetCreate(
            url="https://example.com/news",
            interval_seconds=300,
            discovery_overlap_seconds=-1,
        )
