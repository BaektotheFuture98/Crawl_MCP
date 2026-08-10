from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.engine import RowMapping

from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus, CrawlMode, ErrorCode
from crawling_mcp.domain.models import CrawlFailure, PageItem
from crawling_mcp.domain.monitoring import (
    CrawlChange,
    CrawlJobSummary,
    CrawlSnapshot,
    CrawlTarget,
)

StorageRow = Mapping[str, Any] | RowMapping


def target_from_row(row: StorageRow) -> CrawlTarget:
    options = dict(row["crawl_options"] or {})
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
        **options,
    )


def snapshot_from_row(row: StorageRow) -> CrawlSnapshot:
    return CrawlSnapshot(
        id=row["id"],
        target_id=row["target_id"],
        article_id=row["article_id"],
        url=str(row["url"]),
        content_hash=str(row["content_hash"]),
        title=str(row["title"]),
        content=str(row["content"]),
        source=row["source"],
        etag=row["etag"],
        last_modified=row["last_modified"],
        metadata=dict(row["metadata"] or {}),
        depth=int(row["depth"]),
        collected_at=row["collected_at"],
        last_seen_at=row["last_seen_at"],
    )


def change_from_row(row: StorageRow) -> CrawlChange:
    return CrawlChange(
        id=row["id"],
        target_id=row["target_id"],
        change_type=ChangeType(str(row["change_type"])),
        url=str(row["url"]),
        title=str(row["title"]),
        previous_snapshot_id=row["previous_snapshot_id"],
        current_snapshot_id=row["current_snapshot_id"],
        detected_at=row["detected_at"],
    )


def job_from_row(row: StorageRow) -> CrawlJobSummary:
    return CrawlJobSummary(
        job_id=row["id"],
        target_id=row["target_id"],
        status=CrawlJobStatus(str(row["status"])),
        checked=int(row["visited_pages"]),
        changed=int(row["changed_pages"]),
        new=int(row["new_pages"]),
        updated=int(row["updated_pages"]),
        unchanged=int(row["unchanged_pages"]),
        failed=int(row["failed_pages"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        error=row["error"],
    )


def page_item_from_row(row: StorageRow) -> PageItem:
    return PageItem(
        url=str(row["url"]),
        title=str(row["title"]),
        content=str(row["content"]),
        metadata=dict(row["metadata"] or {}),
        published_at=row["published_at"],
        source=row["source"],
        collected_at=row["collected_at"],
    )


def failure_from_row(row: StorageRow) -> CrawlFailure:
    return CrawlFailure(
        url=str(row["url"]),
        error_code=ErrorCode(str(row["error_code"])),
        message=str(row["message"]),
        details=dict(row["details"] or {}),
        artifacts=dict(row["artifacts"] or {}),
    )
