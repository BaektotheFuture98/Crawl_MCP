from __future__ import annotations

import pytest

from crawling_mcp.adapters.outbound.crawling.adaptive_engine import AdaptiveCrawlerEngine
from crawling_mcp.adapters.outbound.crawling.browser_engine import BrowserCrawlerEngine
from crawling_mcp.adapters.outbound.crawling.factory import CrawlerFactory
from crawling_mcp.adapters.outbound.crawling.http_engine import HttpCrawlerEngine
from crawling_mcp.domain.enums import CrawlMode
from crawling_mcp.domain.errors import AuthenticationRequiredError


def test_factory_returns_requested_strategy_instances() -> None:
    http = object.__new__(HttpCrawlerEngine)
    browser = object.__new__(BrowserCrawlerEngine)
    adaptive = object.__new__(AdaptiveCrawlerEngine)
    factory = CrawlerFactory(http=http, browser=browser, adaptive=adaptive)

    assert factory.get(CrawlMode.HTTP) is http
    assert factory.get(CrawlMode.BROWSER) is browser
    assert factory.get(CrawlMode.AUTO) is adaptive


def test_factory_rejects_http_mode_for_authenticated_request() -> None:
    factory = CrawlerFactory(
        http=object.__new__(HttpCrawlerEngine),
        browser=object.__new__(BrowserCrawlerEngine),
        adaptive=object.__new__(AdaptiveCrawlerEngine),
    )

    with pytest.raises(AuthenticationRequiredError):
        factory.get(CrawlMode.HTTP, authenticated=True)


def test_factory_forces_authenticated_auto_request_to_browser() -> None:
    browser = object.__new__(BrowserCrawlerEngine)
    factory = CrawlerFactory(
        http=object.__new__(HttpCrawlerEngine),
        browser=browser,
        adaptive=object.__new__(AdaptiveCrawlerEngine),
    )

    assert factory.get(CrawlMode.AUTO, authenticated=True) is browser
