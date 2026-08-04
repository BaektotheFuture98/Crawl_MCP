from __future__ import annotations

import pytest

from crawling_mcp.adapters.crawlee.adaptive_engine import AdaptiveCrawlerEngine
from crawling_mcp.domain.models import (
    CrawlContext,
    CrawlRequest,
    CrawlResult,
    PageSnapshot,
    ScrapePageRequest,
)


class FakeEngine:
    def __init__(self, snapshot: PageSnapshot) -> None:
        self.snapshot = snapshot
        self.scrape_calls = 0

    async def scrape(self, request: ScrapePageRequest, context: CrawlContext) -> PageSnapshot:
        self.scrape_calls += 1
        return self.snapshot

    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        return CrawlResult(start_url=request.start_url)


@pytest.mark.asyncio
async def test_adaptive_keeps_meaningful_http_page() -> None:
    http = FakeEngine(
        PageSnapshot(url="https://example.com", html=f"<main>{'content ' * 30}</main>")
    )
    browser = FakeEngine(PageSnapshot(url="https://example.com", html="browser"))
    adaptive = AdaptiveCrawlerEngine(http=http, browser=browser)

    snapshot = await adaptive.scrape(
        ScrapePageRequest(url="https://example.com"), CrawlContext(domain="example.com")
    )

    assert snapshot is http.snapshot
    assert browser.scrape_calls == 0


@pytest.mark.asyncio
async def test_adaptive_falls_back_for_javascript_shell() -> None:
    http = FakeEngine(
        PageSnapshot(url="https://example.com/login", html="<div id='root'></div><script></script>")
    )
    browser = FakeEngine(PageSnapshot(url="https://example.com/home", html="rendered content"))
    adaptive = AdaptiveCrawlerEngine(http=http, browser=browser)

    snapshot = await adaptive.scrape(
        ScrapePageRequest(url="https://example.com"), CrawlContext(domain="example.com")
    )

    assert snapshot is browser.snapshot
    assert browser.scrape_calls == 1
