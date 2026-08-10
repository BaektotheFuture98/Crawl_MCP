from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.engine import RowMapping

from crawling_mcp.domain.articles import Article, ArticleChangeSummary, ArticleCrawlState
from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus, CrawlMode
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


def state_from_row(row: StorageRow) -> ArticleCrawlState:
    change = row["last_change_type"]
    return ArticleCrawlState(
        article_id=row["article_id"],
        target_id=row["target_id"],
        url=str(row["url"]),
        content_hash=str(row["content_hash"]),
        etag=row["etag"],
        last_modified=row["last_modified"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        last_changed_at=row["last_changed_at"],
        last_change_type=ChangeType(str(change)) if change else None,
    )


def run_from_row(row: StorageRow) -> CrawlRun:
    return CrawlRun(
        id=row["id"],
        target_id=row["target_id"],
        status=CrawlJobStatus(str(row["status"])),
        visited_pages=int(row["visited_pages"]),
        new_articles=int(row["new_articles"]),
        updated_articles=int(row["updated_articles"]),
        unchanged_articles=int(row["unchanged_articles"]),
        failed_pages=int(row["failed_pages"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        error=row["error"],
    )


def change_summary_from_row(row: StorageRow) -> ArticleChangeSummary:
    return ArticleChangeSummary(
        article_id=row["article_id"],
        target_id=row["target_id"],
        change_type=ChangeType(str(row["last_change_type"])),
        title=str(row["ar_title"] or ""),
        publisher=row["publisher"],
        url=str(row["url"]),
        published_at=from_article_timestamp(row["published_at"]),
        last_changed_at=row["last_changed_at"],
    )
