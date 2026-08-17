from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, cast
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from crawlee import ConcurrencySettings, Request
from crawlee._types import BasicCrawlingContext
from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext
from crawlee.crawlers._beautifulsoup._beautifulsoup_parser import BeautifulSoupParser
from crawlee.http_clients import HttpResponse
from crawlee.proxy_configuration import ProxyConfiguration
from crawlee.storages import RequestQueue

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
from crawling_mcp.ports.network import EgressProxyPort
from crawling_mcp.ports.robots import RobotsPolicy


class _BoundedBeautifulSoupParser(BeautifulSoupParser):
    def __init__(self, max_content_bytes: int) -> None:
        super().__init__(parser="lxml")
        self._max_content_bytes = max_content_bytes

    async def parse(self, response: HttpResponse) -> BeautifulSoup:
        body = await response.read()
        if len(body) > self._max_content_bytes:
            raise NavigationError(
                reason="response_too_large",
                actual_bytes=len(body),
                max_bytes=self._max_content_bytes,
            )
        return await asyncio.to_thread(BeautifulSoup, body, features="lxml")


class HttpCrawlerEngine:
    """Crawlee BeautifulSoup strategy for static pages."""

    def __init__(
        self,
        *,
        validator: UrlValidator,
        extractors: ExtractorResolver,
        router: PageRouter | None = None,
        egress_proxy: EgressProxyPort | None = None,
        max_content_bytes: int = 10_000_000,
        max_links_per_page: int = 1000,
        robots: RobotsPolicy | None = None,
    ) -> None:
        if max_content_bytes < 1:
            raise ValueError("max_content_bytes must be positive")
        if max_links_per_page < 1:
            raise ValueError("max_links_per_page must be positive")
        self._validator = validator
        self._extractors = extractors
        self._router = router or PageRouter()
        self._egress_proxy = egress_proxy
        self._max_content_bytes = max_content_bytes
        self._max_links_per_page = max_links_per_page
        self._robots = robots

    def _proxy_configuration(self) -> ProxyConfiguration | None:
        if self._egress_proxy is None:
            return None
        return ProxyConfiguration(proxy_urls=[self._egress_proxy.url])

    def _crawler(self, **kwargs: Any) -> BeautifulSoupCrawler:
        crawler = BeautifulSoupCrawler(**kwargs)
        crawler._parser = _BoundedBeautifulSoupParser(self._max_content_bytes)
        return crawler

    def _snapshot(self, context: BeautifulSoupCrawlingContext, *, depth: int) -> PageSnapshot:
        final_url = context.request.loaded_url or context.request.url
        links = [
            urljoin(final_url, str(anchor.get("href")))
            for anchor in context.soup.select("a[href]", limit=self._max_links_per_page)
        ]
        html = str(context.soup)
        encoded_size = len(html.encode("utf-8"))
        if encoded_size > self._max_content_bytes:
            raise NavigationError(
                url=final_url,
                reason="response_too_large",
                actual_bytes=encoded_size,
                max_bytes=self._max_content_bytes,
            )
        return PageSnapshot(
            url=final_url,
            html=html,
            status_code=context.http_response.status_code,
            headers={
                str(key).lower(): str(value) for key, value in context.http_response.headers.items()
            },
            links=links,
            depth=depth,
            not_modified=context.http_response.status_code == 304,
        )

    def _request(
        self,
        url: str,
        *,
        label: str,
        depth: int,
        context: CrawlContext,
    ) -> Request:
        """Build one request with validators from the previous page version."""
        headers: dict[str, str] = {}
        cached = context.cache_entries.get(url) or context.cache_entries.get(
            normalize_url(url, remove_tracking=True)
        )
        if cached is not None:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified
        return Request.from_url(
            url,
            label=label,
            headers=headers,
            user_data={"depth": depth},
        )

    async def scrape(self, request: ScrapePageRequest, context: CrawlContext) -> PageSnapshot:
        """Fetch one static page with Crawlee."""
        snapshots: list[PageSnapshot] = []
        request_queue = await RequestQueue.open(name=f"scrape-{context.job_id}")
        crawler = self._crawler(
            max_requests_per_crawl=1,
            max_request_retries=0,
            request_handler_timeout=timedelta(seconds=request.request_timeout_seconds),
            request_manager=request_queue,
            proxy_configuration=cast(ProxyConfiguration, self._proxy_configuration()),
        )

        @crawler.router.default_handler
        async def handler(crawling_context: BeautifulSoupCrawlingContext) -> None:
            snapshot = self._snapshot(crawling_context, depth=0)
            await self._validator.validate(snapshot.url)
            if snapshot.not_modified and context.not_modified_handler is not None:
                await context.not_modified_handler(snapshot)
            snapshots.append(snapshot)

        try:
            await crawler.run(
                [
                    self._request(
                        request.url,
                        label=PageType.START.value,
                        depth=0,
                        context=context,
                    )
                ]
            )
        finally:
            await request_queue.drop()
        if not snapshots:
            raise NavigationError(url=request.url, reason="no_response")
        return snapshots[0]

    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        """Traverse links with Crawlee's RequestQueue and Router labels."""
        if request.respect_robots_txt:
            if self._robots is None:
                raise NavigationError(
                    url=request.start_url,
                    reason="robots_policy_not_configured",
                )
            if not await self._robots.allowed(request.start_url):
                raise NavigationError(url=request.start_url, reason="robots_disallowed")
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
        request_queue = await RequestQueue.open(name=f"crawl-{context.job_id}")
        crawler = self._crawler(
            max_requests_per_crawl=request.max_pages,
            max_request_retries=request.max_request_retries,
            request_handler_timeout=timedelta(seconds=request.request_timeout_seconds),
            respect_robots_txt_file=False,
            request_manager=request_queue,
            proxy_configuration=cast(ProxyConfiguration, self._proxy_configuration()),
            concurrency_settings=ConcurrencySettings(
                max_concurrency=request.max_concurrency,
                desired_concurrency=request.max_concurrency,
                max_tasks_per_minute=(
                    60 / request.request_delay_seconds
                    if request.request_delay_seconds
                    else float("inf")
                ),
            ),
        )

        async def handle(crawling_context: BeautifulSoupCrawlingContext) -> None:
            depth_value = crawling_context.request.user_data.get("depth", 0)
            depth = int(depth_value) if isinstance(depth_value, int | str) else 0
            snapshot = self._snapshot(crawling_context, depth=depth)
            await self._validator.validate(snapshot.url)
            if snapshot.not_modified:
                if context.not_modified_handler is not None:
                    await context.not_modified_handler(snapshot)
                result.visited_pages += 1
                result.succeeded_pages += 1
                return
            snapshot.page_type = self._router.classify(snapshot, domain=context.domain)
            items = await extractor.extract(snapshot)
            if context.page_handler is not None:
                await context.page_handler(snapshot, items)
            if context.collect_items:
                result.items.extend(items)
            result.visited_pages += 1
            result.succeeded_pages += 1
            if request.request_delay_seconds:
                await asyncio.sleep(request.request_delay_seconds)
            queued: list[Request] = []
            for link in self._router.links(snapshot, domain=context.domain):
                try:
                    normalized = normalize_url(
                        link, remove_tracking=request.remove_tracking_parameters
                    )
                    if not policy.allows(normalized, depth=depth + 1):
                        continue
                    await self._validator.validate(normalized)
                    if (
                        request.respect_robots_txt
                        and self._robots is not None
                        and not await self._robots.allowed(normalized)
                    ):
                        continue
                except CrawlError:
                    continue
                async with reservation_lock:
                    if normalized in seen or len(seen) >= request.max_pages:
                        continue
                    seen.add(normalized)
                label = self._router.classify(
                    PageSnapshot(url=normalized, html=""),
                    domain=context.domain,
                ).value
                queued.append(
                    self._request(
                        normalized,
                        label=label,
                        depth=depth + 1,
                        context=context,
                    )
                )
            if queued:
                await crawling_context.add_requests(queued)

        async def handle_start(crawling_context: BeautifulSoupCrawlingContext) -> None:
            await handle(crawling_context)

        async def handle_list(crawling_context: BeautifulSoupCrawlingContext) -> None:
            await handle(crawling_context)

        async def handle_detail(crawling_context: BeautifulSoupCrawlingContext) -> None:
            await handle(crawling_context)

        crawler.router.default_handler(handle)
        crawler.router.handler(PageType.START.value)(handle_start)
        crawler.router.handler(PageType.LIST.value)(handle_list)
        crawler.router.handler(PageType.DETAIL.value)(handle_detail)

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
            result.visited_pages += 1
            result.failed_pages += 1

        seeds: list[Request] = [
            self._request(
                request.start_url,
                label=PageType.START.value,
                depth=0,
                context=context,
            )
        ]
        for cached in context.cache_entries.values():
            if cached.url == request.start_url or len(seeds) >= request.max_pages:
                continue
            if not policy.allows(cached.url, depth=cached.depth):
                continue
            seen.add(
                normalize_url(
                    cached.url,
                    remove_tracking=request.remove_tracking_parameters,
                )
            )
            label = self._router.classify(
                PageSnapshot(url=cached.url, html=""), domain=context.domain
            ).value
            seeds.append(
                self._request(
                    cached.url,
                    label=label,
                    depth=cached.depth,
                    context=context,
                )
            )
        try:
            await crawler.run(seeds)
        finally:
            await request_queue.drop()
        return result
