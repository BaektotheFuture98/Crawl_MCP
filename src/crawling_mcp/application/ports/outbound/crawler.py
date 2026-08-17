from __future__ import annotations

from typing import Protocol

from crawling_mcp.domain.enums import CrawlMode
from crawling_mcp.domain.models import (
    CrawlContext,
    CrawlRequest,
    CrawlResult,
    PageSnapshot,
    ScrapePageRequest,
    ValidatedUrl,
)


class UrlValidator(Protocol):
    """URL security validation port."""

    async def validate(self, url: str) -> ValidatedUrl: ...


class CrawlerEngine(Protocol):
    """Interchangeable crawl strategy."""

    async def scrape(self, request: ScrapePageRequest, context: CrawlContext) -> PageSnapshot: ...

    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult: ...


class CrawlerEngineFactory(Protocol):
    """Factory port used by the application service."""

    def get(self, mode: CrawlMode, *, authenticated: bool = False) -> CrawlerEngine: ...
