from __future__ import annotations

from datetime import datetime, timedelta

from crawling_mcp.domain.collection.entities import CollectionWindow, as_utc
from crawling_mcp.domain.monitoring import CrawlTarget


class DiscoveryWindowPolicy:
    def calculate(self, *, target: CrawlTarget, now: datetime) -> CollectionWindow:
        current = as_utc(now)
        base = as_utc(target.discovery_watermark_at or target.created_at)
        start = base - timedelta(seconds=target.discovery_overlap_seconds)
        end = current - timedelta(seconds=target.discovery_lag_seconds)
        if end < start:
            end = start
        return CollectionWindow(start=start, end=end)
