from __future__ import annotations

from typing import Protocol, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import create_async_engine

from crawling_mcp.adapters.outbound.artifacts import FailureArtifactWriter
from crawling_mcp.adapters.outbound.authentication.environment_secrets import (
    EnvironmentSecretProvider,
)
from crawling_mcp.adapters.outbound.authentication.example_login import ExampleLoginAdapter
from crawling_mcp.adapters.outbound.authentication.no_auth import NoAuthAdapter
from crawling_mcp.adapters.outbound.authentication.registry import AuthRegistry
from crawling_mcp.adapters.outbound.authentication.saved_session import (
    AuthProfileStore,
    resolve_storage_path,
)
from crawling_mcp.adapters.outbound.browser import BrowserManager
from crawling_mcp.adapters.outbound.crawling.adaptive_engine import AdaptiveCrawlerEngine
from crawling_mcp.adapters.outbound.crawling.browser_engine import BrowserCrawlerEngine
from crawling_mcp.adapters.outbound.crawling.factory import CrawlerFactory
from crawling_mcp.adapters.outbound.crawling.http_engine import HttpCrawlerEngine
from crawling_mcp.adapters.outbound.crawling.router import (
    ExampleNavigationAdapter,
    NavigationRegistry,
    PageRouter,
)
from crawling_mcp.adapters.outbound.extraction.articles import (
    ArticleExtractorRegistry,
    StructuredArticleExtractor,
)
from crawling_mcp.adapters.outbound.extraction.pages.example import ExampleExtractor
from crawling_mcp.adapters.outbound.extraction.pages.generic import GenericExtractor
from crawling_mcp.adapters.outbound.extraction.pages.registry import ExtractorRegistry
from crawling_mcp.adapters.outbound.network.egress_proxy import SafeEgressProxy
from crawling_mcp.adapters.outbound.network.robots import RobotsTxtChecker
from crawling_mcp.adapters.outbound.network.security import UrlSecurityValidator
from crawling_mcp.adapters.outbound.persistence.file_repository import FileRepository
from crawling_mcp.adapters.outbound.persistence.memory_repository import InMemoryRepository
from crawling_mcp.adapters.outbound.persistence.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.adapters.outbound.persistence.postgres import PostgresMonitoringStore
from crawling_mcp.application.article_collection_service import ArticleCollectionService
from crawling_mcp.application.auth_service import AuthService
from crawling_mcp.application.collection_query_service import CollectionQueryService
from crawling_mcp.application.crawl_service import CrawlService
from crawling_mcp.application.ports.outbound.monitoring import MonitoringUnitOfWorkFactory
from crawling_mcp.application.ports.outbound.repository import CrawlRepository
from crawling_mcp.bootstrap.config import Settings
from crawling_mcp.domain.articles import Article
from crawling_mcp.domain.collection import ArticleDiscoverySummary
from crawling_mcp.domain.models import (
    CrawlLimits,
    CrawlRequest,
    CrawlResult,
    PageItem,
    ScrapePageRequest,
    SupportedSite,
)
from crawling_mcp.domain.monitoring import (
    CollectionResult,
    ConfigureTargetRequest,
    CrawlRun,
    CrawlTarget,
)


class MonitoringStore(MonitoringUnitOfWorkFactory, Protocol):
    """Unit-of-work factory with process lifecycle ownership."""

    async def close(self) -> None: ...


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
        article_extractor_registry: ArticleExtractorRegistry,
        auth_service: AuthService,
        crawl_service: CrawlService,
        monitoring_store: MonitoringStore,
        collection_service: ArticleCollectionService,
        collection_query_service: CollectionQueryService,
    ) -> None:
        self.settings = settings
        self.egress_proxy = egress_proxy
        self.browser = browser
        self.auth_registry = auth_registry
        self.extractor_registry = extractor_registry
        self.article_extractor_registry = article_extractor_registry
        self.auth_service = auth_service
        self.crawl_service = crawl_service
        self.monitoring_store = monitoring_store
        self.collection_service = collection_service
        self.collection_query_service = collection_query_service
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
                monitoring_store = getattr(self, "monitoring_store", None)
                if monitoring_store is not None:
                    await monitoring_store.close()
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

    async def list_crawl_targets(self, *, enabled: bool | None, limit: int) -> list[CrawlTarget]:
        return await self.collection_query_service.list_targets(enabled=enabled, limit=limit)

    async def configure_crawl_target(self, request: ConfigureTargetRequest) -> CrawlTarget:
        return await self.collection_query_service.configure_target(request)

    async def run_crawl_target(self, target_id: UUID) -> CollectionResult:
        return await self.collection_query_service.run_target(target_id)

    async def get_crawl_status(self, *, target_id: UUID | None, limit: int) -> list[CrawlRun]:
        return await self.collection_query_service.get_crawl_status(
            target_id=target_id, limit=limit
        )

    async def get_recent_articles(
        self, *, target_id: UUID | None, limit: int
    ) -> list[ArticleDiscoverySummary]:
        return await self.collection_query_service.get_recent_articles(
            target_id=target_id, limit=limit
        )

    async def get_article(self, article_id: UUID) -> Article | None:
        return await self.collection_query_service.get_article(article_id)


def build_container(settings: Settings | None = None) -> ApplicationContainer:
    """Build the dependency graph without starting external resources."""
    configured = settings or Settings()
    validator = UrlSecurityValidator(
        domain_allowlist=configured.domain_allowlist,
        allow_private_networks=configured.allow_private_networks,
        resolver_timeout_seconds=configured.dns_timeout_seconds,
        max_dns_answers=configured.max_dns_answers,
    )
    egress_proxy = SafeEgressProxy(
        validator=validator,
        connect_timeout_seconds=configured.egress_connect_timeout_seconds,
        max_upstream_bytes=configured.max_egress_bytes_per_connection,
    )
    extractors = ExtractorRegistry(default=GenericExtractor())
    article_extractors = ArticleExtractorRegistry(default=StructuredArticleExtractor())
    navigation = NavigationRegistry()
    auth_registry = AuthRegistry(default=NoAuthAdapter())
    profiles = AuthProfileStore.from_yaml(configured.auth_profiles_path)
    for profile_name in profiles.names():
        profile = profiles.get(profile_name)
        if profile.adapter == "example_login":
            auth_registry.register(
                profile.domain, ExampleLoginAdapter(configured.test_site_base_url)
            )
            extractors.register(profile.domain, ExampleExtractor())
            navigation.register(profile.domain, ExampleNavigationAdapter())
    repository: CrawlRepository
    monitoring_store: MonitoringStore
    if configured.repository == "memory":
        repository = InMemoryRepository()
        monitoring_store = cast(MonitoringStore, InMemoryMonitoringStore())
    elif configured.repository == "postgres":
        engine = create_async_engine(configured.postgres_dsn)
        repository = InMemoryRepository()
        monitoring_store = cast(MonitoringStore, PostgresMonitoringStore(engine))
    else:
        repository = FileRepository(configured.data_dir / "results")
        monitoring_store = cast(MonitoringStore, InMemoryMonitoringStore())
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
        secrets=EnvironmentSecretProvider(),
        storage_path_resolver=resolve_storage_path,
        artifacts=artifacts,
    )
    router = PageRouter(registry=navigation)
    robots = RobotsTxtChecker(validator=validator, egress_proxy=egress_proxy)
    http_engine = HttpCrawlerEngine(
        validator=validator,
        extractors=extractors,
        router=router,
        egress_proxy=egress_proxy,
        max_content_bytes=configured.max_content_bytes,
        max_links_per_page=configured.max_links_per_page,
        robots=robots,
    )
    browser_engine = BrowserCrawlerEngine(
        validator=validator,
        extractors=extractors,
        browser=browser,
        router=router,
        artifacts=artifacts,
        robots=robots,
        max_content_bytes=configured.max_content_bytes,
        max_links_per_page=configured.max_links_per_page,
    )
    adaptive_engine = AdaptiveCrawlerEngine(
        http=http_engine,
        browser=browser_engine,
        robots=robots,
    )
    factory = CrawlerFactory(http=http_engine, browser=browser_engine, adaptive=adaptive_engine)
    crawl_service = CrawlService(
        validator=validator,
        factory=factory,
        extractors=extractors,
        repository=repository,
        auth=auth_service,
        limits=CrawlLimits(
            max_pages=configured.max_pages_limit,
            max_depth=configured.max_depth_limit,
            max_request_retries=configured.max_request_retries_limit,
            request_timeout_seconds=configured.request_timeout_limit_seconds,
            job_timeout_seconds=configured.job_timeout_limit_seconds,
            max_concurrency=configured.max_concurrency_limit,
        ),
    )
    collection_service = ArticleCollectionService(
        crawler=crawl_service,
        article_extractors=article_extractors,
        uow_factory=monitoring_store,
        retry_base_seconds=configured.worker_retry_base_seconds,
        retry_max_seconds=configured.worker_retry_max_seconds,
        lease_seconds=configured.worker_lease_seconds,
    )
    collection_query_service = CollectionQueryService(
        uow_factory=monitoring_store,
        monitoring=collection_service,
    )
    return ApplicationContainer(
        settings=configured,
        egress_proxy=egress_proxy,
        browser=browser,
        auth_registry=auth_registry,
        extractor_registry=extractors,
        article_extractor_registry=article_extractors,
        auth_service=auth_service,
        crawl_service=crawl_service,
        monitoring_store=monitoring_store,
        collection_service=collection_service,
        collection_query_service=collection_query_service,
    )


def build_worker_container(settings: Settings | None = None) -> ApplicationContainer:
    """Build a worker process graph that shares durable PostgreSQL state with MCP."""
    configured = settings or Settings()
    if configured.repository != "postgres":
        raise ValueError("crawler worker requires repository=postgres")
    return build_container(configured)
