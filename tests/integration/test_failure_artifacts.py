from __future__ import annotations

from pathlib import Path

import pytest

from crawling_mcp.adapters.crawlee.browser_engine import BrowserCrawlerEngine
from crawling_mcp.adapters.extractors.generic import GenericExtractor
from crawling_mcp.adapters.extractors.registry import ExtractorRegistry
from crawling_mcp.domain.errors import NavigationError
from crawling_mcp.domain.models import CrawlContext, CrawlRequest, ValidatedUrl
from crawling_mcp.infrastructure.artifacts import FailureArtifactWriter
from crawling_mcp.infrastructure.browser import BrowserManager
from crawling_mcp.infrastructure.security import UrlSecurityValidator


class RejectRedirectValidator:
    def __init__(self) -> None:
        self._delegate = UrlSecurityValidator(allow_private_networks=True)
        self._calls = 0

    async def validate(self, url: str) -> ValidatedUrl:
        self._calls += 1
        if self._calls == 2:
            raise NavigationError(url=url, reason="forced_post_navigation_failure")
        return await self._delegate.validate(url)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_browser_failure_saves_html_screenshot_and_accessibility_snapshot(
    test_site_url: str, tmp_path: Path
) -> None:
    browser = BrowserManager(headless=True)
    extractors = ExtractorRegistry(default=GenericExtractor())
    artifacts = FailureArtifactWriter(tmp_path / "failures")
    engine = BrowserCrawlerEngine(
        validator=RejectRedirectValidator(),
        extractors=extractors,
        browser=browser,
        artifacts=artifacts,
    )
    context = CrawlContext(domain="127.0.0.1")
    await browser.start()
    try:
        result = await engine.crawl(
            CrawlRequest(
                start_url=f"{test_site_url}/test-site/login",
                crawl_mode="browser",
                max_pages=1,
                request_delay_seconds=0,
                respect_robots_txt=False,
            ),
            context,
        )
    finally:
        await browser.close()

    assert len(result.failures) == 1
    folder = tmp_path / "failures" / str(context.job_id)
    assert (folder / "error.json").is_file()
    assert (folder / "page.html").is_file()
    assert (folder / "screenshot.png").stat().st_size > 0
    assert (folder / "accessibility_snapshot.txt").is_file()
