from __future__ import annotations

import pytest

from crawling_mcp.adapters.crawlee.adaptive_engine import AdaptiveCrawlerEngine
from crawling_mcp.domain.errors import NavigationError
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
        self.crawl_calls = 0

    async def scrape(self, request: ScrapePageRequest, context: CrawlContext) -> PageSnapshot:
        self.scrape_calls += 1
        return self.snapshot

    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        self.crawl_calls += 1
        return CrawlResult(start_url=request.start_url)


class DenyRobots:
    async def allowed(self, url: str) -> bool:
        return False


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


@pytest.mark.asyncio
async def test_adaptive_site_crawl_uses_probe_to_fallback_for_dynamic_start() -> None:
    http = FakeEngine(
        PageSnapshot(url="https://example.com", html="<div id='root'></div><script></script>")
    )
    browser = FakeEngine(PageSnapshot(url="https://example.com", html="rendered"))
    adaptive = AdaptiveCrawlerEngine(http=http, browser=browser)

    await adaptive.crawl(
        CrawlRequest(start_url="https://example.com", respect_robots_txt=False),
        CrawlContext(domain="example.com"),
    )

    assert http.scrape_calls == 1
    assert http.crawl_calls == 0
    assert browser.crawl_calls == 1


@pytest.mark.asyncio
async def test_adaptive_site_crawl_keeps_http_for_meaningful_start() -> None:
    http = FakeEngine(
        PageSnapshot(url="https://example.com", html=f"<main>{'content ' * 30}</main>")
    )
    browser = FakeEngine(PageSnapshot(url="https://example.com", html="rendered"))
    adaptive = AdaptiveCrawlerEngine(http=http, browser=browser)

    await adaptive.crawl(
        CrawlRequest(start_url="https://example.com", respect_robots_txt=False),
        CrawlContext(domain="example.com"),
    )

    assert http.scrape_calls == 1
    assert http.crawl_calls == 1
    assert browser.crawl_calls == 0


@pytest.mark.asyncio
async def test_adaptive_site_crawl_checks_robots_before_http_probe() -> None:
    http = FakeEngine(PageSnapshot(url="https://example.com", html="public"))
    browser = FakeEngine(PageSnapshot(url="https://example.com", html="rendered"))
    adaptive = AdaptiveCrawlerEngine(http=http, browser=browser, robots=DenyRobots())

    with pytest.raises(NavigationError) as caught:
        await adaptive.crawl(
            CrawlRequest(start_url="https://example.com", respect_robots_txt=True),
            CrawlContext(domain="example.com"),
        )

    assert caught.value.details["reason"] == "robots_disallowed"
    assert http.scrape_calls == 0
    assert browser.crawl_calls == 0


@pytest.mark.asyncio
async def test_adaptive_does_not_fallback_to_browser_for_not_modified_response() -> None:
    http = FakeEngine(
        PageSnapshot(
            url="https://example.com",
            html="",
            status_code=304,
            not_modified=True,
        )
    )
    browser = FakeEngine(PageSnapshot(url="https://example.com", html="rendered"))
    adaptive = AdaptiveCrawlerEngine(http=http, browser=browser)

    snapshot = await adaptive.scrape(
        ScrapePageRequest(url="https://example.com"), CrawlContext(domain="example.com")
    )

    assert snapshot.not_modified
    assert browser.scrape_calls == 0
