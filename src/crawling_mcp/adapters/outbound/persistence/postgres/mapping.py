from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.engine import RowMapping

from crawling_mcp.domain.articles import Article
from crawling_mcp.domain.collection import ArticleDiscovery, ArticleDiscoverySummary
from crawling_mcp.domain.enums import CrawlJobStatus, CrawlMode
from crawling_mcp.domain.monitoring import CrawlRun, CrawlTarget

StorageRow = Mapping[str, Any] | RowMapping
_SEOUL = ZoneInfo("Asia/Seoul")


def to_article_timestamp(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(_SEOUL).replace(tzinfo=None)


def from_article_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_SEOUL)
    return value.astimezone(UTC)


def target_from_row(row: StorageRow) -> CrawlTarget:
    return CrawlTarget(
        id=row["id"],
        url=str(row["url"]),
        interval_seconds=int(row["interval_seconds"]),
        enabled=bool(row["enabled"]),
        crawl_mode=CrawlMode(str(row["crawl_mode"])),
        auth_profile=row["auth_profile"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_crawled_at=row["last_crawled_at"],
        next_crawl_at=row["next_crawl_at"],
        failure_count=int(row["failure_count"]),
        last_error=row["last_error"],
        last_failed_at=row["last_failed_at"],
        next_retry_at=row["next_retry_at"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        discovery_watermark_at=row["discovery_watermark_at"],
        discovery_lag_seconds=int(row["discovery_lag_seconds"]),
        discovery_overlap_seconds=int(row["discovery_overlap_seconds"]),
        **dict(row["crawl_options"] or {}),
    )


def article_from_row(row: StorageRow) -> Article:
    return Article(
        id=row["id"],
        title=str(row["ar_title"] or ""),
        content=str(row["ar_content"] or ""),
        reporter=row["reporter"],
        publisher=row["publisher"],
        url=str(row["url"] or ""),
        published_at=from_article_timestamp(row["published_at"]),
    )


def discovery_from_row(row: StorageRow) -> ArticleDiscovery:
    return ArticleDiscovery(
        article_id=row["article_id"],
        target_id=row["target_id"],
        discovered_at=row["discovered_at"],
    )


def run_from_row(row: StorageRow) -> CrawlRun:
    return CrawlRun(
        id=row["id"],
        target_id=row["target_id"],
        status=CrawlJobStatus(str(row["status"])),
        visited_pages=int(row["visited_pages"]),
        discovered_articles=int(row["discovered_articles"]),
        inserted_articles=int(row["inserted_articles"]),
        duplicate_articles=int(row["duplicate_articles"]),
        failed_pages=int(row["failed_pages"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        error=row["error"],
    )


def discovery_summary_from_row(row: StorageRow) -> ArticleDiscoverySummary:
    return ArticleDiscoverySummary(
        article_id=row["article_id"],
        target_id=row["target_id"],
        title=str(row["ar_title"] or ""),
        publisher=row["publisher"],
        url=str(row["url"]),
        published_at=from_article_timestamp(row["published_at"]),
        discovered_at=row["discovered_at"],
    )
