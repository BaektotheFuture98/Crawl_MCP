from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from mcp.server.fastmcp import FastMCP

from crawling_mcp.adapters.inbound.mcp.tools import register_tools
from crawling_mcp.domain.articles import Article
from crawling_mcp.domain.collection import ArticleDiscoverySummary
from crawling_mcp.domain.enums import CrawlJobStatus
from crawling_mcp.domain.models import PageItem, SupportedSite
from crawling_mcp.domain.monitoring import CollectionResult, CrawlRun, CrawlTarget


class MonitoringApplication:
    def __init__(self) -> None:
        self.target_id = uuid4()
        self.article_id = uuid4()

    async def scrape_page(self, request: Any) -> PageItem:
        return PageItem(url=request.url)

    async def crawl_site(self, request: Any) -> Any:
        raise AssertionError("not used")

    async def validate_session(self, auth_profile: str) -> bool:
        return True

    def list_supported_sites(self) -> list[SupportedSite]:
        return []

    async def list_crawl_targets(self, *, enabled: bool | None, limit: int) -> list[CrawlTarget]:
        return [CrawlTarget(id=self.target_id, url="https://example.com", interval_seconds=60)]

    async def configure_crawl_target(self, request: Any) -> CrawlTarget:
        return (await self.list_crawl_targets(enabled=None, limit=1))[0]

    async def run_crawl_target(self, target_id: UUID) -> CollectionResult:
        return CollectionResult(target_id=target_id, crawl_run_id=uuid4(), visited_pages=1)

    async def get_crawl_status(self, *, target_id: UUID | None, limit: int) -> list[CrawlRun]:
        now = datetime.now(UTC)
        return [
            CrawlRun(
                id=uuid4(),
                target_id=self.target_id,
                status=CrawlJobStatus.COMPLETED,
                visited_pages=100,
                discovered_articles=1,
                inserted_articles=1,
                started_at=now,
                completed_at=now,
            )
        ]

    async def get_recent_articles(
        self, *, target_id: UUID | None, limit: int
    ) -> list[ArticleDiscoverySummary]:
        return [
            ArticleDiscoverySummary(
                article_id=self.article_id,
                target_id=self.target_id,
                url="https://example.com/a",
                title="A",
                publisher="동아일보",
                discovered_at=datetime.now(UTC),
            )
        ]

    async def get_article(self, article_id: UUID) -> Article | None:
        return Article(
            id=article_id,
            url="https://example.com/a",
            title="A",
            content="large body",
            publisher="동아일보",
        )


def structured(result: Any) -> dict[str, Any]:
    assert isinstance(result, tuple)
    assert isinstance(result[1], dict)
    return result[1]


@pytest.mark.asyncio
async def test_recent_article_discoveries_and_status_do_not_return_full_content() -> None:
    server = FastMCP("test")
    application = MonitoringApplication()
    register_tools(server, application)

    recent = structured(await server.call_tool("get_recent_articles", {"limit": 10}))
    status = structured(await server.call_tool("get_crawl_status", {}))

    assert recent["count"] == 1
    assert recent["articles"][0]["title"] == "A"
    assert "large body" not in str(recent)
    assert status["jobs"][0]["visited_pages"] == 100
    assert status["jobs"][0]["inserted_articles"] == 1
    assert "content" not in str(status).lower()


@pytest.mark.asyncio
async def test_get_article_returns_content_only_when_explicitly_requested() -> None:
    server = FastMCP("test")
    application = MonitoringApplication()
    register_tools(server, application)

    detail = structured(
        await server.call_tool("get_article", {"article_id": str(application.article_id)})
    )

    assert detail["ar_content"] == "large body"
