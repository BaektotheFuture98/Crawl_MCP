from __future__ import annotations

from pathlib import Path

import pytest

from crawling_mcp.adapters.crawlee.http_engine import HttpCrawlerEngine
from crawling_mcp.adapters.crawlee.router import PageRouter
from crawling_mcp.adapters.extractors.example import ExampleExtractor
from crawling_mcp.adapters.extractors.generic import GenericExtractor
from crawling_mcp.adapters.extractors.registry import ExtractorRegistry
from crawling_mcp.domain.models import (
    CrawlCacheEntry,
    CrawlContext,
    CrawlRequest,
    PageItem,
    PageSnapshot,
    ScrapePageRequest,
)
from crawling_mcp.infrastructure.security import UrlSecurityValidator


def make_engine() -> HttpCrawlerEngine:
    validator = UrlSecurityValidator(allow_private_networks=True)
    extractors = ExtractorRegistry(default=GenericExtractor())
    extractors.register("127.0.0.1", ExampleExtractor())
    return HttpCrawlerEngine(validator=validator, extractors=extractors, router=PageRouter())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_http_page_handler_failure_propagates_to_caller(test_site_url: str) -> None:
    async def fail_persistence(snapshot: PageSnapshot, items: list[PageItem]) -> None:
        del snapshot, items
        raise ConnectionError("database unavailable")

    with pytest.raises(ConnectionError, match="database unavailable"):
        await make_engine().crawl(
            CrawlRequest(
                start_url=f"{test_site_url}/test-site/login",
                crawl_mode="http",
                max_pages=1,
                max_depth=0,
                max_request_retries=0,
                respect_robots_txt=False,
                request_delay_seconds=0,
            ),
            CrawlContext(
                domain="127.0.0.1",
                page_handler=fail_persistence,
            ),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_public_login_page_can_be_scraped(test_site_url: str) -> None:
    engine = make_engine()
    context = CrawlContext(domain="127.0.0.1")

    snapshot = await engine.scrape(
        ScrapePageRequest(url=f"{test_site_url}/test-site/login", crawl_mode="http"),
        context,
    )

    assert snapshot.status_code == 200
    assert "개발용 로그인" in snapshot.html
    assert not (Path("storage/request_queues") / f"scrape-{context.job_id}").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_http_crawl_respects_max_pages(test_site_url: str) -> None:
    engine = make_engine()

    result = await engine.crawl(
        CrawlRequest(
            start_url=f"{test_site_url}/test-site/login",
            crawl_mode="http",
            max_pages=1,
            max_depth=2,
            respect_robots_txt=False,
            request_delay_seconds=0,
        ),
        CrawlContext(domain="127.0.0.1"),
    )

    assert len(result.items) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_http_conditional_request_returns_not_modified_observation(
    test_site_url: str,
) -> None:
    engine = make_engine()
    url = f"{test_site_url}/test-site/cacheable"
    first = await engine.scrape(
        ScrapePageRequest(url=url, crawl_mode="http"),
        CrawlContext(domain="127.0.0.1"),
    )
    observed: list[PageSnapshot] = []

    async def not_modified(snapshot: PageSnapshot) -> None:
        observed.append(snapshot)

    second = await engine.scrape(
        ScrapePageRequest(url=url, crawl_mode="http"),
        CrawlContext(
            domain="127.0.0.1",
            cache_entries={
                url: CrawlCacheEntry(
                    url=url,
                    etag=first.headers["etag"],
                    last_modified=first.headers["last-modified"],
                )
            },
            not_modified_handler=not_modified,
        ),
    )

    assert second.status_code == 304
    assert second.not_modified
    assert observed == [second]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_http_not_modified_handler_failure_propagates_to_caller(
    test_site_url: str,
) -> None:
    engine = make_engine()
    url = f"{test_site_url}/test-site/cacheable"
    first = await engine.scrape(
        ScrapePageRequest(url=url, crawl_mode="http"),
        CrawlContext(domain="127.0.0.1"),
    )

    async def fail_persistence(snapshot: PageSnapshot) -> None:
        del snapshot
        raise ConnectionError("database unavailable")

    with pytest.raises(ConnectionError, match="database unavailable"):
        await engine.scrape(
            ScrapePageRequest(url=url, crawl_mode="http"),
            CrawlContext(
                domain="127.0.0.1",
                cache_entries={
                    url: CrawlCacheEntry(
                        url=url,
                        etag=first.headers["etag"],
                        last_modified=first.headers["last-modified"],
                    )
                },
                not_modified_handler=fail_persistence,
            ),
        )
