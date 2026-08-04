from __future__ import annotations

from bs4 import BeautifulSoup

from crawling_mcp.domain.enums import CrawlMode
from crawling_mcp.domain.errors import CrawlError, NavigationError
from crawling_mcp.domain.models import (
    CrawlContext,
    CrawlRequest,
    CrawlResult,
    PageSnapshot,
    ScrapePageRequest,
)
from crawling_mcp.ports.crawler import CrawlerEngine
from crawling_mcp.ports.robots import RobotsPolicy


class AdaptiveCrawlerEngine:
    """Try low-cost HTTP crawling and fall back to a browser when needed."""

    def __init__(
        self,
        *,
        http: CrawlerEngine,
        browser: CrawlerEngine,
        robots: RobotsPolicy | None = None,
    ) -> None:
        self._http = http
        self._browser = browser
        self._robots = robots

    @staticmethod
    def _needs_browser(snapshot: PageSnapshot) -> bool:
        soup = BeautifulSoup(snapshot.html, "lxml")
        for tag in soup.select("script, style, noscript"):
            tag.decompose()
        text = " ".join(soup.get_text(" ", strip=True).split())
        has_shell = soup.select_one("#root, #app, [data-reactroot]") is not None
        auth_redirect = "/login" in snapshot.url.lower()
        return auth_redirect or has_shell or len(text) < 80

    async def scrape(self, request: ScrapePageRequest, context: CrawlContext) -> PageSnapshot:
        """Fetch through HTTP and retry once with a browser for dynamic content."""
        snapshot = await self._http.scrape(request, context)
        if self._needs_browser(snapshot):
            return await self._browser.scrape(request, context)
        return snapshot

    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        """Probe the start page and choose one traversal strategy for the job."""
        if request.respect_robots_txt:
            if self._robots is None:
                raise NavigationError(
                    url=request.start_url,
                    reason="robots_policy_not_configured",
                )
            if not await self._robots.allowed(request.start_url):
                raise NavigationError(url=request.start_url, reason="robots_disallowed")
        probe_request = ScrapePageRequest(
            url=request.start_url,
            crawl_mode=CrawlMode.HTTP,
            request_timeout_seconds=request.request_timeout_seconds,
        )
        try:
            probe = await self._http.scrape(probe_request, context)
        except CrawlError:
            return await self._browser.crawl(request, context)
        if self._needs_browser(probe):
            return await self._browser.crawl(request, context)
        result = await self._http.crawl(request, context)
        if not result.items and result.failures:
            return await self._browser.crawl(request, context)
        return result
