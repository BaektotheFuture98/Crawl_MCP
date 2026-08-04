from __future__ import annotations

import asyncio

from crawling_mcp.domain.errors import (
    AuthenticationRequiredError,
    ExtractionError,
    NavigationError,
)
from crawling_mcp.domain.models import (
    CrawlContext,
    CrawlRequest,
    CrawlResult,
    PageItem,
    PageSnapshot,
    ScrapePageRequest,
)
from crawling_mcp.ports.authentication import AuthContextProvider
from crawling_mcp.ports.crawler import CrawlerEngine, CrawlerEngineFactory, UrlValidator
from crawling_mcp.ports.extractor import ExtractorResolver
from crawling_mcp.ports.repository import CrawlRepository


class CrawlService:
    """Application service orchestrating validation, crawl and persistence."""

    def __init__(
        self,
        *,
        validator: UrlValidator,
        factory: CrawlerEngineFactory,
        extractors: ExtractorResolver,
        repository: CrawlRepository,
        auth: AuthContextProvider | None = None,
    ) -> None:
        self._validator = validator
        self._factory = factory
        self._extractors = extractors
        self._repository = repository
        self._auth = auth

    async def _scrape_with_context(
        self,
        request: ScrapePageRequest,
        context: CrawlContext,
        engine: CrawlerEngine,
    ) -> PageSnapshot:
        if request.auth_profile is None:
            return await engine.scrape(request, context)
        if self._auth is None:
            raise AuthenticationRequiredError(reason="auth_service_not_configured")
        async with self._auth.context_for(context.domain, request.auth_profile) as browser_context:
            context.authenticated = True
            context.browser_context = browser_context
            return await engine.scrape(request, context)

    async def _crawl_with_context(
        self,
        request: CrawlRequest,
        context: CrawlContext,
        engine: CrawlerEngine,
    ) -> CrawlResult:
        if request.auth_profile is None:
            return await engine.crawl(request, context)
        if self._auth is None:
            raise AuthenticationRequiredError(reason="auth_service_not_configured")
        async with self._auth.context_for(context.domain, request.auth_profile) as browser_context:
            context.authenticated = True
            context.browser_context = browser_context
            return await engine.crawl(request, context)

    async def scrape_page(self, request: ScrapePageRequest) -> PageItem:
        """Validate, fetch and extract one page."""
        validated = await self._validator.validate(request.url)
        authenticated = request.auth_profile is not None
        extractor = self._extractors.get(validated.hostname, authenticated=authenticated)
        engine = self._factory.get(request.crawl_mode, authenticated=authenticated)
        context = CrawlContext(domain=validated.hostname, adapter_name=extractor.name)
        safe_request = request.model_copy(update={"url": validated.url})
        try:
            snapshot = await asyncio.wait_for(
                self._scrape_with_context(safe_request, context, engine),
                timeout=request.request_timeout_seconds,
            )
        except TimeoutError as error:
            raise NavigationError(url=validated.url, reason="request_timeout") from error
        await self._validator.validate(snapshot.url)
        items = await extractor.extract(snapshot)
        if not items:
            raise ExtractionError(url=snapshot.url, reason="no_items")
        return items[0]

    async def crawl_site(self, request: CrawlRequest) -> CrawlResult:
        """Run a bounded crawl and persist its aggregate result."""
        validated = await self._validator.validate(request.start_url)
        authenticated = request.auth_profile is not None
        extractor = self._extractors.get(validated.hostname, authenticated=authenticated)
        engine = self._factory.get(request.crawl_mode, authenticated=authenticated)
        context = CrawlContext(domain=validated.hostname, adapter_name=extractor.name)
        initial = CrawlResult(job_id=context.job_id, start_url=validated.url)
        await self._repository.start_job(initial)
        safe_request = request.model_copy(update={"start_url": validated.url})
        try:
            result = await asyncio.wait_for(
                self._crawl_with_context(safe_request, context, engine),
                timeout=request.job_timeout_seconds,
            )
        except TimeoutError as error:
            raise NavigationError(url=validated.url, reason="job_timeout") from error
        for item in result.items:
            await self._repository.save_page(context.job_id, item)
        for failure in result.failures:
            await self._repository.save_failure(context.job_id, failure)
        await self._repository.complete_job(context.job_id)
        stored = await self._repository.get_job(context.job_id)
        if stored is None:
            raise NavigationError(url=validated.url, reason="result_not_persisted")
        return stored

    async def close(self) -> None:
        """Close application-owned persistence resources."""
        await self._repository.close()
