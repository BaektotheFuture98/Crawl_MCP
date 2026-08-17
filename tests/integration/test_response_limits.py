from __future__ import annotations

import pytest

from crawling_mcp.adapters.outbound.browser import BrowserManager
from crawling_mcp.adapters.outbound.crawling.browser_engine import BrowserCrawlerEngine
from crawling_mcp.adapters.outbound.crawling.http_engine import HttpCrawlerEngine
from crawling_mcp.adapters.outbound.extraction.pages.generic import GenericExtractor
from crawling_mcp.adapters.outbound.extraction.pages.registry import ExtractorRegistry
from crawling_mcp.adapters.outbound.network.security import UrlSecurityValidator
from crawling_mcp.domain.errors import NavigationError
from crawling_mcp.domain.models import CrawlContext, ScrapePageRequest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_http_and_browser_reject_oversized_html(test_site_url: str) -> None:
    validator = UrlSecurityValidator(allow_private_networks=True)
    extractors = ExtractorRegistry(default=GenericExtractor())
    http = HttpCrawlerEngine(
        validator=validator,
        extractors=extractors,
        max_content_bytes=100,
    )
    browser_manager = BrowserManager()
    browser = BrowserCrawlerEngine(
        validator=validator,
        extractors=extractors,
        browser=browser_manager,
        max_content_bytes=100,
    )
    request = ScrapePageRequest(url=f"{test_site_url}/test-site/login")

    await browser_manager.start()
    try:
        with pytest.raises(NavigationError):
            await http.scrape(request, CrawlContext(domain="127.0.0.1"))
        with pytest.raises(NavigationError) as caught:
            await browser.scrape(
                request.model_copy(update={"crawl_mode": "browser"}),
                CrawlContext(domain="127.0.0.1"),
            )
        assert caught.value.details["reason"] == "response_too_large"
    finally:
        await browser_manager.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_http_and_browser_bound_discovered_links(test_site_url: str) -> None:
    validator = UrlSecurityValidator(allow_private_networks=True)
    extractors = ExtractorRegistry(default=GenericExtractor())
    http = HttpCrawlerEngine(
        validator=validator,
        extractors=extractors,
        max_links_per_page=1,
    )
    browser_manager = BrowserManager()
    browser = BrowserCrawlerEngine(
        validator=validator,
        extractors=extractors,
        browser=browser_manager,
        max_links_per_page=1,
    )
    request = ScrapePageRequest(url=f"{test_site_url}/test-site/many-links")

    await browser_manager.start()
    try:
        http_snapshot = await http.scrape(request, CrawlContext(domain="127.0.0.1"))
        browser_snapshot = await browser.scrape(
            request.model_copy(update={"crawl_mode": "browser"}),
            CrawlContext(domain="127.0.0.1"),
        )
    finally:
        await browser_manager.close()

    assert len(http_snapshot.links) == 1
    assert len(browser_snapshot.links) == 1
