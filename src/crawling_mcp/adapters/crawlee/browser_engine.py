from __future__ import annotations

import asyncio
from urllib.parse import urljoin

import structlog
from playwright.async_api import BrowserContext, Page

from crawling_mcp.adapters.crawlee.router import PageRouter
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
from crawling_mcp.infrastructure.logging import mask_sensitive
from crawling_mcp.ports.artifacts import FailureArtifactPort
from crawling_mcp.ports.browser import BrowserManagerPort
from crawling_mcp.ports.crawler import UrlValidator
from crawling_mcp.ports.extractor import ExtractorResolver
from crawling_mcp.ports.robots import RobotsPolicy


class BrowserCrawlerEngine:
    """Shared-Playwright-browser strategy for rendered pages."""

    def __init__(
        self,
        *,
        validator: UrlValidator,
        extractors: ExtractorResolver,
        browser: BrowserManagerPort,
        router: PageRouter | None = None,
        artifacts: FailureArtifactPort | None = None,
        robots: RobotsPolicy | None = None,
    ) -> None:
        self._validator = validator
        self._extractors = extractors
        self._browser = browser
        self._router = router or PageRouter()
        self._artifacts = artifacts
        self._robots = robots
        self._log = structlog.get_logger(__name__)

    async def _capture_artifacts(
        self, context: CrawlContext, error: CrawlError, page: Page
    ) -> dict[str, str]:
        if self._artifacts is None:
            return {}
        try:
            paths = await self._artifacts.capture(context.job_id, error, page=page)
        except Exception as artifact_error:
            self._log.error(
                "crawl_artifact_capture_failed",
                job_id=str(context.job_id),
                error_type=type(artifact_error).__name__,
            )
            return {}
        return {key: value for key, value in paths.model_dump().items() if value is not None}

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
            await self._capture_artifacts(context, domain_error, page)
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
        seen_lock = asyncio.Lock()
        result_lock = asyncio.Lock()
        pace_lock = asyncio.Lock()
        next_request_at = 0.0

        async def pace() -> None:
            nonlocal next_request_at
            if not request.request_delay_seconds:
                return
            async with pace_lock:
                loop = asyncio.get_running_loop()
                wait_seconds = next_request_at - loop.time()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                next_request_at = loop.time() + request.request_delay_seconds

        async def process(url: str, depth: int) -> None:
            page = await browser_context.new_page()
            try:
                if request.respect_robots_txt:
                    if self._robots is None:
                        raise NavigationError(url=url, reason="robots_policy_not_configured")
                    if not await self._robots.allowed(url):
                        raise NavigationError(url=url, reason="robots_disallowed")
                snapshot: PageSnapshot | None = None
                last_error: Exception | None = None
                for attempt in range(request.max_request_retries + 1):
                    try:
                        await pace()
                        snapshot = await self._navigate(page, url, request.request_timeout_seconds)
                        break
                    except Exception as error:
                        last_error = error
                        if attempt >= request.max_request_retries:
                            raise
                if snapshot is None:
                    raise NavigationError(
                        url=url,
                        reason=(type(last_error).__name__ if last_error else "no_response"),
                    )
                snapshot.depth = depth
                snapshot.page_type = self._router.classify(snapshot, domain=context.domain)
                items = await extractor.extract(snapshot)
                async with result_lock:
                    result.items.extend(items)
                    result.visited_pages += 1
                    result.succeeded_pages += 1
                for link in self._router.links(snapshot, domain=context.domain):
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
                    async with seen_lock:
                        if normalized in seen or len(seen) >= request.max_pages:
                            continue
                        seen.add(normalized)
                    await queue.put((normalized, depth + 1))
            except Exception as error:
                domain_error = (
                    error
                    if isinstance(error, CrawlError)
                    else NavigationError(url=url, reason=type(error).__name__)
                )
                artifact_values = await self._capture_artifacts(context, domain_error, page)
                async with result_lock:
                    result.failures.append(
                        CrawlFailure(
                            url=url,
                            error_code=domain_error.code,
                            message=domain_error.message,
                            details=mask_sensitive(domain_error.details),
                            artifacts=artifact_values,
                        )
                    )
                    result.visited_pages += 1
                    result.failed_pages += 1
            finally:
                await page.close()

        async def worker() -> None:
            while True:
                url, depth = await queue.get()
                try:
                    await process(url, depth)
                finally:
                    queue.task_done()

        workers = [
            asyncio.create_task(worker())
            for _ in range(min(request.max_concurrency, request.max_pages))
        ]
        try:
            await queue.join()
        finally:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
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
