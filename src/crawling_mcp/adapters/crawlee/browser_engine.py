from __future__ import annotations

import asyncio
from urllib.parse import urljoin

from playwright.async_api import BrowserContext, Page

from crawling_mcp.adapters.crawlee.router import PageRouter
from crawling_mcp.domain.enums import ErrorCode
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
from crawling_mcp.infrastructure.artifacts import FailureArtifactWriter
from crawling_mcp.ports.browser import BrowserManagerPort
from crawling_mcp.ports.crawler import UrlValidator
from crawling_mcp.ports.extractor import ExtractorResolver


class BrowserCrawlerEngine:
    """Shared-Playwright-browser strategy for rendered pages."""

    def __init__(
        self,
        *,
        validator: UrlValidator,
        extractors: ExtractorResolver,
        browser: BrowserManagerPort,
        router: PageRouter | None = None,
        artifacts: FailureArtifactWriter | None = None,
    ) -> None:
        self._validator = validator
        self._extractors = extractors
        self._browser = browser
        self._router = router or PageRouter()
        self._artifacts = artifacts

    async def _navigate(self, page: Page, url: str, timeout_seconds: int) -> PageSnapshot:
        await self._validator.validate(url)
        response = await page.goto(
            url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000
        )
        await self._validator.validate(page.url)
        html = await page.content()
        links = await page.locator("a[href]").evaluate_all(
            "els => els.map(el => el.href).filter(Boolean)"
        )
        return PageSnapshot(
            url=page.url,
            html=html,
            status_code=response.status if response else None,
            links=[str(link) for link in links],
        )

    async def _scrape_in_context(
        self,
        browser_context: BrowserContext,
        request: ScrapePageRequest,
        context: CrawlContext,
    ) -> PageSnapshot:
        page = await browser_context.new_page()
        try:
            return await self._navigate(page, request.url, request.request_timeout_seconds)
        except Exception as error:
            domain_error = (
                error
                if isinstance(error, CrawlError)
                else NavigationError(url=request.url, reason=type(error).__name__)
            )
            if self._artifacts is not None:
                await self._artifacts.capture(context.job_id, domain_error, page=page)
            raise domain_error from error
        finally:
            await page.close()

    async def scrape(self, request: ScrapePageRequest, context: CrawlContext) -> PageSnapshot:
        """Render one page in an isolated BrowserContext."""
        if context.browser_context is not None:
            return await self._scrape_in_context(context.browser_context, request, context)
        async with self._browser.context() as browser_context:
            return await self._scrape_in_context(browser_context, request, context)

    async def _crawl_in_context(
        self, browser_context: BrowserContext, request: CrawlRequest, context: CrawlContext
    ) -> CrawlResult:
        result = CrawlResult(job_id=context.job_id, start_url=request.start_url)
        extractor = self._extractors.get(context.domain, authenticated=context.authenticated)
        policy = LinkPolicy(
            start_url=request.start_url,
            max_depth=request.max_depth,
            same_domain_only=request.same_domain_only,
            include_patterns=request.include_patterns,
            exclude_patterns=request.exclude_patterns,
        )
        queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        await queue.put((request.start_url, 0))
        seen = {
            normalize_url(request.start_url, remove_tracking=request.remove_tracking_parameters)
        }
        while not queue.empty() and len(result.items) + len(result.failures) < request.max_pages:
            url, depth = await queue.get()
            page = await browser_context.new_page()
            try:
                snapshot = await self._navigate(page, url, request.request_timeout_seconds)
                snapshot.depth = depth
                snapshot.page_type = self._router.classify(snapshot)
                result.items.extend(await extractor.extract(snapshot))
                for link in snapshot.links:
                    try:
                        normalized = normalize_url(
                            urljoin(snapshot.url, link),
                            remove_tracking=request.remove_tracking_parameters,
                        )
                        if normalized in seen or not policy.allows(normalized, depth=depth + 1):
                            continue
                        await self._validator.validate(normalized)
                    except CrawlError:
                        continue
                    if len(seen) >= request.max_pages:
                        break
                    seen.add(normalized)
                    await queue.put((normalized, depth + 1))
                if request.request_delay_seconds:
                    await asyncio.sleep(request.request_delay_seconds)
            except Exception as error:
                domain_error = (
                    error
                    if isinstance(error, CrawlError)
                    else NavigationError(url=url, reason=type(error).__name__)
                )
                artifact_values: dict[str, str] = {}
                if self._artifacts is not None:
                    artifact_paths = await self._artifacts.capture(
                        context.job_id, domain_error, page=page
                    )
                    artifact_values = {
                        key: value
                        for key, value in artifact_paths.model_dump().items()
                        if value is not None
                    }
                result.failures.append(
                    CrawlFailure(
                        url=url,
                        error_code=ErrorCode.NAVIGATION_ERROR,
                        message="페이지에 접속하지 못했습니다.",
                        details={"error_type": type(error).__name__},
                        artifacts=artifact_values,
                    )
                )
            finally:
                await page.close()
        return result

    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        """Traverse rendered pages with an isolated or authenticated context."""
        try:
            if context.browser_context is not None:
                return await self._crawl_in_context(context.browser_context, request, context)
            async with self._browser.context() as browser_context:
                return await self._crawl_in_context(browser_context, request, context)
        except TimeoutError as error:
            raise NavigationError(url=request.start_url, reason="browser_timeout") from error
