from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from crawling_mcp.adapters.auth.example_login import ExampleLoginAdapter
from crawling_mcp.adapters.auth.no_auth import NoAuthAdapter
from crawling_mcp.adapters.auth.registry import AuthRegistry
from crawling_mcp.adapters.auth.saved_session import AuthProfileStore
from crawling_mcp.adapters.crawlee.browser_engine import BrowserCrawlerEngine
from crawling_mcp.adapters.extractors.example import ExampleExtractor
from crawling_mcp.adapters.extractors.generic import GenericExtractor
from crawling_mcp.adapters.extractors.registry import ExtractorRegistry
from crawling_mcp.application.auth_service import AuthService
from crawling_mcp.domain.errors import AuthenticationFailedError
from crawling_mcp.domain.models import (
    AuthProfile,
    CrawlContext,
    CrawlRequest,
    Credentials,
    ScrapePageRequest,
)
from crawling_mcp.infrastructure.artifacts import FailureArtifactWriter
from crawling_mcp.infrastructure.browser import BrowserManager
from crawling_mcp.infrastructure.robots import RobotsTxtChecker
from crawling_mcp.infrastructure.security import UrlSecurityValidator


class FixedSecrets:
    def __init__(self, username: str = "test-user", password: str = "test-password") -> None:
        self._credentials = Credentials(username=username, password=password)

    def credentials(self, username_env: str, password_env: str) -> Credentials:
        return self._credentials


def make_auth_stack(
    base_url: str,
    tmp_path: Path,
    *,
    secrets: FixedSecrets | None = None,
    login_variant: str | None = None,
) -> tuple[BrowserManager, AuthService, BrowserCrawlerEngine, Path]:
    state_path = tmp_path / "auth" / "reader.json"
    profile = AuthProfile(
        domain="127.0.0.1",
        adapter="example_login",
        username_env="TEST_SITE_USERNAME",
        password_env="TEST_SITE_PASSWORD",
        storage_state_path=str(state_path),
    )
    auth_registry = AuthRegistry(default=NoAuthAdapter())
    auth_registry.register("127.0.0.1", ExampleLoginAdapter(base_url, login_variant=login_variant))
    extractors = ExtractorRegistry(default=GenericExtractor())
    extractors.register("127.0.0.1", ExampleExtractor())
    browser = BrowserManager(headless=True, max_contexts=2)
    auth = AuthService(
        profiles=AuthProfileStore({"reader": profile}),
        registry=auth_registry,
        browser=browser,
        auth_root=state_path.parent,
        secrets=secrets or FixedSecrets(),
        artifacts=FailureArtifactWriter(tmp_path / "failures"),
    )
    validator = UrlSecurityValidator(allow_private_networks=True)
    engine = BrowserCrawlerEngine(
        validator=validator,
        extractors=extractors,
        browser=browser,
        robots=RobotsTxtChecker(validator=validator),
    )
    return browser, auth, engine, state_path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_protected_scrape_saves_and_reuses_session(
    test_site_url: str, tmp_path: Path
) -> None:
    browser, auth, engine, state_path = make_auth_stack(test_site_url, tmp_path)
    await browser.start()
    try:
        for _ in range(2):
            async with auth.context_for("127.0.0.1", "reader") as browser_context:
                snapshot = await engine.scrape(
                    ScrapePageRequest(
                        url=f"{test_site_url}/test-site/list",
                        crawl_mode="browser",
                        auth_profile="reader",
                    ),
                    CrawlContext(
                        domain="127.0.0.1",
                        authenticated=True,
                        browser_context=browser_context,
                    ),
                )
                assert "상세 1" in snapshot.html
        async with httpx.AsyncClient(base_url=test_site_url) as client:
            count = await client.get("/__test__/login-count")
        assert count.json() == {"login_count": 1}
        assert state_path.is_file()
        assert await auth.validate_session("reader") is True
    finally:
        await browser.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expired_session_triggers_relogin(test_site_url: str, tmp_path: Path) -> None:
    browser, auth, _, _ = make_auth_stack(test_site_url, tmp_path)
    await browser.start()
    try:
        async with auth.context_for("127.0.0.1", "reader"):
            pass
        async with httpx.AsyncClient(base_url=test_site_url) as client:
            await client.post("/__test__/expire-sessions")
        async with auth.context_for("127.0.0.1", "reader"):
            pass
        async with httpx.AsyncClient(base_url=test_site_url) as client:
            count = await client.get("/__test__/login-count")
        assert count.json() == {"login_count": 2}
    finally:
        await browser.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticated_list_traverses_detail_links(
    test_site_url: str, tmp_path: Path
) -> None:
    browser, auth, engine, _ = make_auth_stack(test_site_url, tmp_path)
    await browser.start()
    try:
        async with auth.context_for("127.0.0.1", "reader") as browser_context:
            result = await engine.crawl(
                CrawlRequest(
                    start_url=f"{test_site_url}/test-site/list",
                    crawl_mode="browser",
                    auth_profile="reader",
                    max_pages=3,
                    max_depth=1,
                    request_delay_seconds=0,
                    respect_robots_txt=False,
                ),
                CrawlContext(
                    domain="127.0.0.1",
                    authenticated=True,
                    browser_context=browser_context,
                ),
            )
        assert len(result.items) == 3
        assert {item.metadata.get("id") for item in result.items} >= {"1", "2"}
    finally:
        await browser.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invalid_login_credentials_return_domain_error(
    test_site_url: str, tmp_path: Path
) -> None:
    browser, auth, _, _ = make_auth_stack(
        test_site_url, tmp_path, secrets=FixedSecrets(password="wrong")
    )
    await browser.start()
    try:
        with pytest.raises(AuthenticationFailedError):
            async with auth.context_for("127.0.0.1", "reader"):
                pass
    finally:
        await browser.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_login_ui_returns_authentication_failure(
    test_site_url: str, tmp_path: Path
) -> None:
    browser, auth, _, _ = make_auth_stack(test_site_url, tmp_path, login_variant="missing")
    await browser.start()
    job_id = uuid4()
    try:
        with pytest.raises(AuthenticationFailedError) as error:
            async with auth.context_for("127.0.0.1", "reader", job_id):
                pass
        assert error.value.details["reason"] == "locator_not_found"
        folder = tmp_path / "failures" / str(job_id)
        assert (folder / "error.json").is_file()
        assert (folder / "page.html").is_file()
        assert (folder / "screenshot.png").stat().st_size > 0
        assert (folder / "accessibility_snapshot.txt").is_file()
    finally:
        await browser.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_max_depth_zero_does_not_visit_detail_links(
    test_site_url: str, tmp_path: Path
) -> None:
    browser, auth, engine, _ = make_auth_stack(test_site_url, tmp_path)
    await browser.start()
    try:
        async with auth.context_for("127.0.0.1", "reader") as browser_context:
            result = await engine.crawl(
                CrawlRequest(
                    start_url=f"{test_site_url}/test-site/list",
                    crawl_mode="browser",
                    auth_profile="reader",
                    max_pages=3,
                    max_depth=0,
                    request_delay_seconds=0,
                    respect_robots_txt=False,
                ),
                CrawlContext(
                    domain="127.0.0.1",
                    authenticated=True,
                    browser_context=browser_context,
                ),
            )
        assert len(result.items) == 1
        assert result.items[0].title == "목록"
    finally:
        await browser.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_browser_crawl_respects_robots_txt(test_site_url: str, tmp_path: Path) -> None:
    browser, auth, engine, _ = make_auth_stack(test_site_url, tmp_path)
    await browser.start()
    try:
        async with auth.context_for("127.0.0.1", "reader") as browser_context:
            result = await engine.crawl(
                CrawlRequest(
                    start_url=f"{test_site_url}/test-site/list",
                    crawl_mode="browser",
                    auth_profile="reader",
                    max_pages=3,
                    max_depth=1,
                    request_delay_seconds=0,
                    respect_robots_txt=True,
                ),
                CrawlContext(
                    domain="127.0.0.1",
                    authenticated=True,
                    browser_context=browser_context,
                ),
            )
        titles = {item.title for item in result.items}
        assert "목록" in titles
        assert "상세 1" in titles
        assert "상세 2" not in titles
    finally:
        await browser.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_browser_crawl_honors_max_concurrency(test_site_url: str, tmp_path: Path) -> None:
    browser, auth, engine, _ = make_auth_stack(test_site_url, tmp_path)
    await browser.start()
    try:
        async with auth.context_for("127.0.0.1", "reader") as browser_context:
            result = await engine.crawl(
                CrawlRequest(
                    start_url=f"{test_site_url}/test-site/concurrency-list",
                    crawl_mode="browser",
                    auth_profile="reader",
                    max_pages=3,
                    max_depth=1,
                    max_concurrency=2,
                    request_delay_seconds=0,
                    respect_robots_txt=False,
                ),
                CrawlContext(
                    domain="127.0.0.1",
                    authenticated=True,
                    browser_context=browser_context,
                ),
            )
        async with httpx.AsyncClient(base_url=test_site_url) as client:
            observed = (await client.get("/__test__/max-active")).json()
        assert result.visited_pages == 3
        assert observed["max_active_requests"] == 2
    finally:
        await browser.close()
