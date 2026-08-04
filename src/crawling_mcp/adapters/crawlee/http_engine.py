from __future__ import annotations

import asyncio
from datetime import timedelta
from urllib.parse import urljoin

from crawlee import ConcurrencySettings, Request
from crawlee._types import BasicCrawlingContext
from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext

from crawling_mcp.adapters.crawlee.router import PageRouter
from crawling_mcp.domain.enums import ErrorCode, PageType
from crawling_mcp.domain.errors import CrawlError, NavigationError
from crawling_mcp.domain.models import (
    CrawlContext,
    CrawlFailure,
    CrawlRequest,
    CrawlResult,
    PageSnapshot,
    ScrapePageRequest,
)
from crawling_mcp.domain.policies import LinkPolicy, normalize_url
from crawling_mcp.ports.crawler import UrlValidator
from crawling_mcp.ports.extractor import ExtractorResolver


class HttpCrawlerEngine:
    """Crawlee BeautifulSoup strategy for static pages."""

    def __init__(
        self,
        *,
        validator: UrlValidator,
        extractors: ExtractorResolver,
        router: PageRouter | None = None,
    ) -> None:
        self._validator = validator
        self._extractors = extractors
        self._router = router or PageRouter()

    @staticmethod
    def _snapshot(context: BeautifulSoupCrawlingContext, *, depth: int) -> PageSnapshot:
        final_url = context.request.loaded_url or context.request.url
        links = [
            urljoin(final_url, str(anchor.get("href"))) for anchor in context.soup.select("a[href]")
        ]
        return PageSnapshot(
            url=final_url,
            html=str(context.soup),
            status_code=context.http_response.status_code,
            links=links,
            depth=depth,
        )

    async def scrape(self, request: ScrapePageRequest, context: CrawlContext) -> PageSnapshot:
        """Fetch one static page with Crawlee."""
        snapshots: list[PageSnapshot] = []
        crawler = BeautifulSoupCrawler(
            max_requests_per_crawl=1,
            max_request_retries=0,
            request_handler_timeout=timedelta(seconds=request.request_timeout_seconds),
        )

        @crawler.router.default_handler
        async def handler(crawling_context: BeautifulSoupCrawlingContext) -> None:
            snapshot = self._snapshot(crawling_context, depth=0)
            await self._validator.validate(snapshot.url)
            snapshots.append(snapshot)

        await crawler.run([request.url])
        if not snapshots:
            raise NavigationError(url=request.url, reason="no_response")
        return snapshots[0]

    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        """Traverse links with Crawlee's RequestQueue and Router labels."""
        result = CrawlResult(job_id=context.job_id, start_url=request.start_url)
        policy = LinkPolicy(
            start_url=request.start_url,
            max_depth=request.max_depth,
            same_domain_only=request.same_domain_only,
            include_patterns=request.include_patterns,
            exclude_patterns=request.exclude_patterns,
        )
        extractor = self._extractors.get(context.domain, authenticated=False)
        seen = {
            normalize_url(request.start_url, remove_tracking=request.remove_tracking_parameters)
        }
        reservation_lock = asyncio.Lock()
        crawler = BeautifulSoupCrawler(
            max_requests_per_crawl=request.max_pages,
            max_request_retries=request.max_request_retries,
            request_handler_timeout=timedelta(seconds=request.request_timeout_seconds),
            respect_robots_txt_file=request.respect_robots_txt,
            concurrency_settings=ConcurrencySettings(
                max_concurrency=request.max_concurrency,
                desired_concurrency=request.max_concurrency,
            ),
        )

        async def handle(crawling_context: BeautifulSoupCrawlingContext) -> None:
            depth_value = crawling_context.request.user_data.get("depth", 0)
            depth = int(depth_value) if isinstance(depth_value, int | str) else 0
            snapshot = self._snapshot(crawling_context, depth=depth)
            await self._validator.validate(snapshot.url)
            snapshot.page_type = self._router.classify(snapshot)
            result.items.extend(await extractor.extract(snapshot))
            if request.request_delay_seconds:
                await asyncio.sleep(request.request_delay_seconds)
            queued: list[Request] = []
            for link in snapshot.links:
                try:
                    normalized = normalize_url(
                        link, remove_tracking=request.remove_tracking_parameters
                    )
                    if not policy.allows(normalized, depth=depth + 1):
                        continue
                    await self._validator.validate(normalized)
                except CrawlError:
                    continue
                async with reservation_lock:
                    if normalized in seen or len(seen) >= request.max_pages:
                        continue
                    seen.add(normalized)
                label = self._router.classify(PageSnapshot(url=normalized, html="")).value
                queued.append(
                    Request.from_url(
                        normalized,
                        label=label,
                        user_data={"depth": depth + 1},
                    )
                )
            if queued:
                await crawling_context.add_requests(queued)

        crawler.router.default_handler(handle)
        for label in PageType:
            crawler.router.handler(label.value)(handle)

        @crawler.failed_request_handler
        async def failed(
            crawling_context: BeautifulSoupCrawlingContext | BasicCrawlingContext,
            error: Exception,
        ) -> None:
            result.failures.append(
                CrawlFailure(
                    url=crawling_context.request.url,
                    error_code=ErrorCode.NAVIGATION_ERROR,
                    message="페이지에 접속하지 못했습니다.",
                    details={"error_type": type(error).__name__},
                )
            )

        start = Request.from_url(
            request.start_url,
            label=PageType.START.value,
            user_data={"depth": 0},
        )
        await crawler.run([start])
        return result
