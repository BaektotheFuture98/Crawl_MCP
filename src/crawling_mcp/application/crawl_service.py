from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import structlog

from crawling_mcp.domain.errors import (
    AuthenticationRequiredError,
    CrawlError,
    CrawlLimitExceededError,
    ExtractionError,
    NavigationError,
)
from crawling_mcp.domain.models import (
    CrawlContext,
    CrawlExecution,
    CrawlFailure,
    CrawlLimits,
    CrawlRequest,
    CrawlResult,
    PageItem,
    PageSnapshot,
    ScrapePageRequest,
    utc_now,
)
from crawling_mcp.infrastructure.logging import mask_sensitive
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
        limits: CrawlLimits | None = None,
    ) -> None:
        self._validator = validator
        self._factory = factory
        self._extractors = extractors
        self._repository = repository
        self._auth = auth
        self._limits = limits or CrawlLimits()
        self._log = structlog.get_logger(__name__)

    def _enforce_scrape_limits(self, request: ScrapePageRequest) -> None:
        if request.request_timeout_seconds > self._limits.request_timeout_seconds:
            raise CrawlLimitExceededError(
                field="request_timeout_seconds",
                requested=request.request_timeout_seconds,
                allowed=self._limits.request_timeout_seconds,
            )

    def _enforce_crawl_limits(self, request: CrawlRequest) -> None:
        checks = {
            "max_pages": (request.max_pages, self._limits.max_pages),
            "max_depth": (request.max_depth, self._limits.max_depth),
            "max_request_retries": (
                request.max_request_retries,
                self._limits.max_request_retries,
            ),
            "request_timeout_seconds": (
                request.request_timeout_seconds,
                self._limits.request_timeout_seconds,
            ),
            "job_timeout_seconds": (
                request.job_timeout_seconds,
                self._limits.job_timeout_seconds,
            ),
            "max_concurrency": (request.max_concurrency, self._limits.max_concurrency),
        }
        for field, (requested, allowed) in checks.items():
            if requested > allowed:
                raise CrawlLimitExceededError(
                    field=field,
                    requested=requested,
                    allowed=allowed,
                )

    async def _persist_terminal_failure(self, *, job_id: UUID, url: str, error: CrawlError) -> None:
        """Best-effort persistence of one terminal job failure."""
        failure = CrawlFailure(
            url=url,
            error_code=error.code,
            message=error.message,
            details=mask_sensitive(error.details),
        )
        try:
            await self._repository.save_failure(job_id, failure)
            await self._repository.set_counts(
                job_id,
                visited_pages=1,
                succeeded_pages=0,
                failed_pages=1,
            )
            await self._repository.complete_job(job_id)
        except Exception as persistence_error:
            self._log.error(
                "terminal_failure_persistence_failed",
                job_id=str(job_id),
                error_type=type(persistence_error).__name__,
            )

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
        async with self._auth.context_for(
            context.domain, request.auth_profile, context.job_id
        ) as browser_context:
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
        async with self._auth.context_for(
            context.domain, request.auth_profile, context.job_id
        ) as browser_context:
            context.authenticated = True
            context.browser_context = browser_context
            return await engine.crawl(request, context)

    async def _run_scrape_page(self, request: ScrapePageRequest, job_id: UUID) -> PageItem:
        validated = await self._validator.validate(request.url)
        authenticated = request.auth_profile is not None
        extractor = self._extractors.get(validated.hostname, authenticated=authenticated)
        engine = self._factory.get(request.crawl_mode, authenticated=authenticated)
        context = CrawlContext(
            job_id=job_id,
            domain=validated.hostname,
            adapter_name=extractor.name,
        )
        log_context = {
            "job_id": str(context.job_id),
            "url": validated.url,
            "domain": validated.hostname,
            "adapter_name": extractor.name,
        }
        self._log.info("scrape_started", **log_context)
        safe_request = request.model_copy(update={"url": validated.url})
        try:
            snapshot = await asyncio.wait_for(
                self._scrape_with_context(safe_request, context, engine),
                timeout=request.request_timeout_seconds,
            )
            await self._validator.validate(snapshot.url)
            try:
                items = await extractor.extract(snapshot)
            except CrawlError:
                raise
            except Exception as error:
                raise ExtractionError(url=snapshot.url, reason=type(error).__name__) from error
            if not items:
                raise ExtractionError(url=snapshot.url, reason="no_items")
        except TimeoutError as error:
            self._log.warning("scrape_failed", error_code="NAVIGATION_ERROR", **log_context)
            domain_error = NavigationError(
                url=validated.url,
                reason="request_timeout",
                job_id=context.job_id,
            )
            raise domain_error from error
        except CrawlError as error:
            error.attach_job_id(context.job_id)
            self._log.warning("scrape_failed", error_code=error.code, **log_context)
            raise
        for item in items:
            await self._repository.save_page(context.job_id, item)
        await self._repository.set_counts(
            context.job_id,
            visited_pages=1,
            succeeded_pages=1,
            failed_pages=0,
        )
        await self._repository.complete_job(context.job_id)
        self._log.info("scrape_completed", final_url=snapshot.url, **log_context)
        return items[0]

    async def scrape_page(self, request: ScrapePageRequest) -> PageItem:
        """Run a single-page job under one end-to-end deadline."""
        self._enforce_scrape_limits(request)
        job_id = uuid4()
        try:
            async with asyncio.timeout(request.request_timeout_seconds):
                await self._repository.start_job(CrawlResult(job_id=job_id, start_url=request.url))
                return await self._run_scrape_page(request, job_id)
        except TimeoutError as error:
            domain_error = NavigationError(
                url=request.url,
                reason="request_timeout",
                job_id=job_id,
            )
            await self._persist_terminal_failure(job_id=job_id, url=request.url, error=domain_error)
            raise domain_error from error
        except CrawlError as error:
            error.attach_job_id(job_id)
            await self._persist_terminal_failure(job_id=job_id, url=request.url, error=error)
            raise
        except Exception as error:
            domain_error = NavigationError(
                url=request.url,
                reason="internal_error",
                job_id=job_id,
            )
            await self._persist_terminal_failure(job_id=job_id, url=request.url, error=domain_error)
            raise domain_error from error

    async def _run_crawl_site(
        self, request: CrawlRequest, job_id: UUID, execution: CrawlExecution | None
    ) -> CrawlResult:
        validated = await self._validator.validate(request.start_url)
        authenticated = request.auth_profile is not None
        extractor = self._extractors.get(validated.hostname, authenticated=authenticated)
        engine = self._factory.get(request.crawl_mode, authenticated=authenticated)
        context = CrawlContext(
            job_id=job_id,
            domain=validated.hostname,
            adapter_name=extractor.name,
            cache_entries=execution.cache_entries if execution is not None else {},
            page_handler=execution.page_handler if execution is not None else None,
            not_modified_handler=(
                execution.not_modified_handler if execution is not None else None
            ),
        )
        log_context = {
            "job_id": str(context.job_id),
            "url": validated.url,
            "domain": validated.hostname,
            "adapter_name": extractor.name,
        }
        self._log.info("crawl_started", **log_context)
        safe_request = request.model_copy(update={"start_url": validated.url})
        try:
            result = await asyncio.wait_for(
                self._crawl_with_context(safe_request, context, engine),
                timeout=request.job_timeout_seconds,
            )
        except TimeoutError as error:
            self._log.warning("crawl_failed", error_code="NAVIGATION_ERROR", **log_context)
            domain_error = NavigationError(
                url=validated.url,
                reason="job_timeout",
                job_id=context.job_id,
            )
            raise domain_error from error
        except CrawlError as error:
            error.attach_job_id(context.job_id)
            self._log.warning("crawl_failed", error_code=error.code, **log_context)
            raise
        if execution is not None and not execution.persist_result:
            completed = result.model_copy(update={"completed_at": result.completed_at or utc_now()})
            self._log.info(
                "crawl_completed",
                visited_pages=completed.visited_pages,
                succeeded_pages=completed.succeeded_pages,
                failed_pages=completed.failed_pages,
                persisted=False,
                **log_context,
            )
            return completed
        for item in result.items:
            await self._repository.save_page(context.job_id, item)
        for failure in result.failures:
            await self._repository.save_failure(context.job_id, failure)
        await self._repository.set_counts(
            context.job_id,
            visited_pages=result.visited_pages,
            succeeded_pages=result.succeeded_pages,
            failed_pages=result.failed_pages,
        )
        await self._repository.complete_job(context.job_id)
        stored = await self._repository.get_job(context.job_id)
        if stored is None:
            raise NavigationError(url=validated.url, reason="result_not_persisted")
        self._log.info(
            "crawl_completed",
            visited_pages=stored.visited_pages,
            succeeded_pages=stored.succeeded_pages,
            failed_pages=stored.failed_pages,
            **log_context,
        )
        return stored

    async def crawl_site(
        self, request: CrawlRequest, *, execution: CrawlExecution | None = None
    ) -> CrawlResult:
        """Run a bounded crawl job under one end-to-end deadline."""
        self._enforce_crawl_limits(request)
        job_id = execution.job_id if execution is not None and execution.job_id else uuid4()
        persist_result = execution is None or execution.persist_result
        try:
            async with asyncio.timeout(request.job_timeout_seconds):
                if persist_result:
                    await self._repository.start_job(
                        CrawlResult(job_id=job_id, start_url=request.start_url)
                    )
                return await self._run_crawl_site(request, job_id, execution)
        except TimeoutError as error:
            domain_error = NavigationError(
                url=request.start_url,
                reason="job_timeout",
                job_id=job_id,
            )
            if persist_result:
                await self._persist_terminal_failure(
                    job_id=job_id, url=request.start_url, error=domain_error
                )
            raise domain_error from error
        except CrawlError as error:
            error.attach_job_id(job_id)
            if persist_result:
                await self._persist_terminal_failure(
                    job_id=job_id, url=request.start_url, error=error
                )
            raise
        except Exception as error:
            domain_error = NavigationError(
                url=request.start_url,
                reason="internal_error",
                job_id=job_id,
            )
            if persist_result:
                await self._persist_terminal_failure(
                    job_id=job_id, url=request.start_url, error=domain_error
                )
            raise domain_error from error

    async def close(self) -> None:
        """Close application-owned persistence resources."""
        await self._repository.close()
