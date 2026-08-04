from __future__ import annotations

from crawling_mcp.adapters.auth.example_login import ExampleLoginAdapter
from crawling_mcp.adapters.auth.no_auth import NoAuthAdapter
from crawling_mcp.adapters.auth.registry import AuthRegistry
from crawling_mcp.adapters.auth.saved_session import AuthProfileStore
from crawling_mcp.adapters.crawlee.adaptive_engine import AdaptiveCrawlerEngine
from crawling_mcp.adapters.crawlee.browser_engine import BrowserCrawlerEngine
from crawling_mcp.adapters.crawlee.factory import CrawlerFactory
from crawling_mcp.adapters.crawlee.http_engine import HttpCrawlerEngine
from crawling_mcp.adapters.crawlee.router import PageRouter
from crawling_mcp.adapters.extractors.example import ExampleExtractor
from crawling_mcp.adapters.extractors.generic import GenericExtractor
from crawling_mcp.adapters.extractors.registry import ExtractorRegistry
from crawling_mcp.adapters.storage.file_repository import FileRepository
from crawling_mcp.adapters.storage.memory_repository import InMemoryRepository
from crawling_mcp.application.auth_service import AuthService
from crawling_mcp.application.crawl_service import CrawlService
from crawling_mcp.domain.models import (
    CrawlRequest,
    CrawlResult,
    PageItem,
    ScrapePageRequest,
    SupportedSite,
)
from crawling_mcp.infrastructure.artifacts import FailureArtifactWriter
from crawling_mcp.infrastructure.browser import BrowserManager
from crawling_mcp.infrastructure.config import Settings
from crawling_mcp.infrastructure.egress_proxy import SafeEgressProxy
from crawling_mcp.infrastructure.security import UrlSecurityValidator
from crawling_mcp.ports.repository import CrawlRepository


class ApplicationContainer:
    """Composition root and lifecycle owner for all long-lived dependencies."""

    def __init__(
        self,
        *,
        settings: Settings,
        egress_proxy: SafeEgressProxy,
        browser: BrowserManager,
        auth_registry: AuthRegistry,
        extractor_registry: ExtractorRegistry,
        auth_service: AuthService,
        crawl_service: CrawlService,
    ) -> None:
        self.settings = settings
        self.egress_proxy = egress_proxy
        self.browser = browser
        self.auth_registry = auth_registry
        self.extractor_registry = extractor_registry
        self.auth_service = auth_service
        self.crawl_service = crawl_service
        self._started = False

    async def start(self) -> None:
        """Start the shared Playwright browser once."""
        if self._started:
            return
        await self.egress_proxy.start()
        try:
            await self.browser.start()
        except Exception:
            await self.egress_proxy.close()
            raise
        self._started = True

    async def close(self) -> None:
        """Close services and the shared browser in dependency order."""
        try:
            await self.crawl_service.close()
        finally:
            try:
                await self.browser.close()
            finally:
                await self.egress_proxy.close()
                self._started = False

    async def scrape_page(self, request: ScrapePageRequest) -> PageItem:
        """Delegate one-page collection to the application service."""
        return await self.crawl_service.scrape_page(request)

    async def crawl_site(self, request: CrawlRequest) -> CrawlResult:
        """Delegate bounded traversal to the application service."""
        return await self.crawl_service.crawl_site(request)

    async def validate_session(self, auth_profile: str) -> bool:
        """Validate a stored authentication session."""
        return await self.auth_service.validate_session(auth_profile)

    def list_supported_sites(self) -> list[SupportedSite]:
        """Combine authentication and extractor registry metadata."""
        auth = self.auth_registry.metadata()
        extractors = self.extractor_registry.metadata()
        return [
            SupportedSite(
                domain=domain,
                authentication=auth.get(domain, "no_auth"),
                extractor=extractors.get(domain, "generic"),
            )
            for domain in sorted(set(auth) | set(extractors))
        ]


def build_container(settings: Settings | None = None) -> ApplicationContainer:
    """Build the dependency graph without starting external resources."""
    configured = settings or Settings()
    validator = UrlSecurityValidator(
        domain_allowlist=configured.domain_allowlist,
        allow_private_networks=configured.allow_private_networks,
    )
    egress_proxy = SafeEgressProxy(validator=validator)
    extractors = ExtractorRegistry(default=GenericExtractor())
    auth_registry = AuthRegistry(default=NoAuthAdapter())
    profiles = AuthProfileStore.from_yaml(configured.auth_profiles_path)
    for profile_name in profiles.names():
        profile = profiles.get(profile_name)
        if profile.adapter == "example_login":
            auth_registry.register(
                profile.domain, ExampleLoginAdapter(configured.test_site_base_url)
            )
            extractors.register(profile.domain, ExampleExtractor())
    repository: CrawlRepository
    if configured.repository == "memory":
        repository = InMemoryRepository()
    else:
        repository = FileRepository(configured.data_dir / "results")
    browser = BrowserManager(
        headless=configured.browser_headless,
        max_contexts=configured.browser_max_contexts,
        egress_proxy=egress_proxy,
    )
    artifacts = FailureArtifactWriter(configured.data_dir / "failures")
    auth_service = AuthService(
        profiles=profiles,
        registry=auth_registry,
        browser=browser,
        auth_root=configured.data_dir / "auth",
        artifacts=artifacts,
    )
    router = PageRouter()
    http_engine = HttpCrawlerEngine(
        validator=validator,
        extractors=extractors,
        router=router,
        egress_proxy=egress_proxy,
    )
    browser_engine = BrowserCrawlerEngine(
        validator=validator,
        extractors=extractors,
        browser=browser,
        router=router,
        artifacts=artifacts,
    )
    adaptive_engine = AdaptiveCrawlerEngine(http=http_engine, browser=browser_engine)
    factory = CrawlerFactory(http=http_engine, browser=browser_engine, adaptive=adaptive_engine)
    crawl_service = CrawlService(
        validator=validator,
        factory=factory,
        extractors=extractors,
        repository=repository,
        auth=auth_service,
    )
    return ApplicationContainer(
        settings=configured,
        egress_proxy=egress_proxy,
        browser=browser,
        auth_registry=auth_registry,
        extractor_registry=extractors,
        auth_service=auth_service,
        crawl_service=crawl_service,
    )
