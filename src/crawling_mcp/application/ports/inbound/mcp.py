from __future__ import annotations

from typing import Protocol
from uuid import UUID

from crawling_mcp.domain.articles import Article
from crawling_mcp.domain.collection import ArticleDiscoverySummary
from crawling_mcp.domain.models import (
    CrawlRequest,
    CrawlResult,
    PageItem,
    ScrapePageRequest,
    SupportedSite,
)
from crawling_mcp.domain.monitoring import (
    CollectionResult,
    ConfigureTargetRequest,
    CrawlRun,
    CrawlTarget,
)


class McpApplication(Protocol):
    async def scrape_page(self, request: ScrapePageRequest) -> PageItem: ...

    async def crawl_site(self, request: CrawlRequest) -> CrawlResult: ...

    async def validate_session(self, auth_profile: str) -> bool: ...

    def list_supported_sites(self) -> list[SupportedSite]: ...

    async def list_crawl_targets(
        self, *, enabled: bool | None, limit: int
    ) -> list[CrawlTarget]: ...

    async def configure_crawl_target(self, request: ConfigureTargetRequest) -> CrawlTarget: ...

    async def run_crawl_target(self, target_id: UUID) -> CollectionResult: ...

    async def get_crawl_status(self, *, target_id: UUID | None, limit: int) -> list[CrawlRun]: ...

    async def get_recent_articles(
        self, *, target_id: UUID | None, limit: int
    ) -> list[ArticleDiscoverySummary]: ...

    async def get_article(self, article_id: UUID) -> Article | None: ...
