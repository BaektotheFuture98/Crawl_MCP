from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from mcp.server.fastmcp import FastMCP

from crawling_mcp.adapters.mcp.tools import register_tools
from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus
from crawling_mcp.domain.models import PageItem, SupportedSite
from crawling_mcp.domain.monitoring import (
    CrawlChange,
    CrawlChangeDetail,
    CrawlJobSummary,
    CrawlSnapshot,
    CrawlTarget,
    MonitoringRunResult,
)


class MonitoringApplication:
    def __init__(self) -> None:
        self.target_id = uuid4()
        self.snapshot_id = uuid4()
        self.change_id = uuid4()

    async def scrape_page(self, request: Any) -> PageItem:
        return PageItem(url=request.url)

    async def crawl_site(self, request: Any) -> Any:
        raise AssertionError("not used")

    async def validate_session(self, auth_profile: str) -> bool:
        return True

    def list_supported_sites(self) -> list[SupportedSite]:
        return []

    async def list_crawl_targets(self, *, enabled: bool | None, limit: int) -> list[CrawlTarget]:
        return [
            CrawlTarget(
                id=self.target_id,
                url="https://example.com",
                interval_seconds=60,
            )
        ]

    async def configure_crawl_target(self, request: Any) -> CrawlTarget:
        return (await self.list_crawl_targets(enabled=None, limit=1))[0]

    async def run_crawl_target(self, target_id: UUID) -> MonitoringRunResult:
        return MonitoringRunResult(target_id=target_id, job_id=uuid4(), checked=1)

    async def get_crawl_status(
        self, *, target_id: UUID | None, limit: int
    ) -> list[CrawlJobSummary]:
        return [
            CrawlJobSummary(
                job_id=uuid4(),
                target_id=self.target_id,
                status=CrawlJobStatus.COMPLETED,
                checked=100,
                changed=1,
            )
        ]

    async def get_recent_changes(self, *, target_id: UUID | None, limit: int) -> list[CrawlChange]:
        return [
            CrawlChange(
                id=self.change_id,
                target_id=self.target_id,
                change_type=ChangeType.NEW,
                url="https://example.com/a",
                title="A",
                current_snapshot_id=self.snapshot_id,
            )
        ]

    async def get_change_detail(self, change_id: UUID) -> CrawlChangeDetail | None:
        change = (await self.get_recent_changes(target_id=None, limit=1))[0]
        return CrawlChangeDetail(
            change=change,
            snapshot=CrawlSnapshot(
                id=self.snapshot_id,
                target_id=self.target_id,
                url=change.url,
                content_hash="a" * 64,
                title="A",
                content="large body",
                collected_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
            ),
        )


def structured(result: Any) -> dict[str, Any]:
    assert isinstance(result, tuple)
    assert isinstance(result[1], dict)
    return result[1]


@pytest.mark.asyncio
async def test_recent_changes_and_status_do_not_return_full_content() -> None:
    server = FastMCP("test")
    application = MonitoringApplication()
    register_tools(server, application)

    recent = structured(await server.call_tool("get_recent_changes", {"limit": 10}))
    status = structured(await server.call_tool("get_crawl_status", {}))

    assert recent["count"] == 1
    assert recent["changes"][0]["title"] == "A"
    assert "content" not in str(recent).lower()
    assert status["jobs"][0]["checked"] == 100
    assert "content" not in str(status).lower()


@pytest.mark.asyncio
async def test_change_detail_returns_content_only_when_explicitly_requested() -> None:
    server = FastMCP("test")
    application = MonitoringApplication()
    register_tools(server, application)

    detail = structured(
        await server.call_tool("get_change_detail", {"change_id": str(application.change_id)})
    )

    assert detail["snapshot"]["content"] == "large body"
