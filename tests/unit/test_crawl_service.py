from __future__ import annotations

import asyncio

import pytest

from crawling_mcp.adapters.extractors.generic import GenericExtractor
from crawling_mcp.adapters.extractors.registry import ExtractorRegistry
from crawling_mcp.adapters.storage.memory_repository import InMemoryRepository
from crawling_mcp.application.crawl_service import CrawlService
from crawling_mcp.domain.enums import CrawlMode
from crawling_mcp.domain.errors import CrawlLimitExceededError, NavigationError
from crawling_mcp.domain.models import (
    CrawlContext,
    CrawlLimits,
    CrawlRequest,
    CrawlResult,
    PageItem,
    PageSnapshot,
    ScrapePageRequest,
    ValidatedUrl,
)


class RecordingValidator:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def validate(self, url: str) -> ValidatedUrl:
        self.urls.append(url)
        return ValidatedUrl(url=url, hostname="example.com", port=443, addresses=("93.184.216.34",))


class SlowValidator(RecordingValidator):
    async def validate(self, url: str) -> ValidatedUrl:
        await asyncio.sleep(1)
        return await super().validate(url)


class FakeEngine:
    async def scrape(self, request: ScrapePageRequest, context: CrawlContext) -> PageSnapshot:
        return PageSnapshot(
            url="https://example.com/final",
            status_code=200,
            html="<html><title>Example</title><body><main>Hello</main></body></html>",
        )

    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        return CrawlResult(start_url=request.start_url)


class FailingEngine(FakeEngine):
    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        raise NavigationError(url=request.start_url, reason="test_failure")


class PersistThenFailEngine(FakeEngine):
    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        item = PageItem(url=request.start_url, title="committed")
        snapshot = PageSnapshot(url=request.start_url, html="<html>committed</html>")
        assert context.page_handler is not None
        await context.page_handler(snapshot, [item])
        raise NavigationError(url=request.start_url, reason="timeout_after_commit")


class MultiItemEngine(FakeEngine):
    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        items = [
            PageItem(url=request.start_url, title="one"),
            PageItem(url=request.start_url, title="two"),
        ]
        snapshot = PageSnapshot(
            url=request.start_url,
            html="<html><main>one two</main></html>",
        )
        assert context.page_handler is not None
        await context.page_handler(snapshot, items)
        return CrawlResult(
            job_id=context.job_id,
            start_url=request.start_url,
            visited_pages=1,
            succeeded_pages=1,
            items=items,
        )


class FakeFactory:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine
        self.calls: list[tuple[CrawlMode, bool]] = []

    def get(self, mode: CrawlMode, *, authenticated: bool = False) -> FakeEngine:
        self.calls.append((mode, authenticated))
        return self.engine


@pytest.mark.asyncio
async def test_scrape_page_validates_initial_and_redirect_urls_before_extracting() -> None:
    validator = RecordingValidator()
    factory = FakeFactory(FakeEngine())
    repository = InMemoryRepository()
    registry = ExtractorRegistry(default=GenericExtractor())
    service = CrawlService(
        validator=validator,
        factory=factory,
        extractors=registry,
        repository=repository,
    )

    item = await service.scrape_page(ScrapePageRequest(url="https://example.com/start"))

    assert validator.urls == ["https://example.com/start", "https://example.com/final"]
    assert item.title == "Example"
    assert item.content == "Hello"
    assert factory.calls == [(CrawlMode.AUTO, False)]


@pytest.mark.asyncio
async def test_crawl_site_persists_engine_result() -> None:
    validator = RecordingValidator()
    engine = FakeEngine()
    factory = FakeFactory(engine)
    repository = InMemoryRepository()
    service = CrawlService(
        validator=validator,
        factory=factory,
        extractors=ExtractorRegistry(default=GenericExtractor()),
        repository=repository,
    )

    result = await service.crawl_site(CrawlRequest(start_url="https://example.com"))
    stored = await repository.get_job(result.job_id)

    assert stored is not None
    assert stored.completed_at is not None
    assert validator.urls == ["https://example.com"]


@pytest.mark.asyncio
async def test_crawl_site_persists_and_correlates_terminal_failure() -> None:
    repository = InMemoryRepository()
    service = CrawlService(
        validator=RecordingValidator(),
        factory=FakeFactory(FailingEngine()),
        extractors=ExtractorRegistry(default=GenericExtractor()),
        repository=repository,
    )

    with pytest.raises(NavigationError) as caught:
        await service.crawl_site(CrawlRequest(start_url="https://example.com"))

    assert caught.value.job_id is not None
    stored = await repository.get_job(caught.value.job_id)
    assert stored is not None
    assert stored.completed_at is not None
    assert stored.failed_pages == 1
    assert stored.failures[0].details["reason"] == "test_failure"


@pytest.mark.asyncio
async def test_terminal_failure_does_not_recount_an_already_committed_page() -> None:
    repository = InMemoryRepository()
    service = CrawlService(
        validator=RecordingValidator(),
        factory=FakeFactory(PersistThenFailEngine()),
        extractors=ExtractorRegistry(default=GenericExtractor()),
        repository=repository,
    )

    with pytest.raises(NavigationError) as caught:
        await service.crawl_site(CrawlRequest(start_url="https://example.com"))

    assert caught.value.job_id is not None
    stored = await repository.get_job(caught.value.job_id)
    assert stored is not None
    assert stored.visited_pages == 1
    assert stored.succeeded_pages == 1
    assert stored.failed_pages == 0
    assert [item.title for item in stored.items] == ["committed"]
    assert len(stored.failures) == 1


@pytest.mark.asyncio
async def test_crawl_service_rejects_request_above_operational_limit() -> None:
    validator = RecordingValidator()
    service = CrawlService(
        validator=validator,
        factory=FakeFactory(FakeEngine()),
        extractors=ExtractorRegistry(default=GenericExtractor()),
        repository=InMemoryRepository(),
        limits=CrawlLimits(max_pages=5),
    )

    with pytest.raises(CrawlLimitExceededError) as caught:
        await service.crawl_site(CrawlRequest(start_url="https://example.com", max_pages=6))

    assert caught.value.details == {"field": "max_pages", "requested": 6, "allowed": 5}
    assert validator.urls == []


@pytest.mark.asyncio
async def test_crawl_service_counts_pages_independently_from_extracted_items() -> None:
    service = CrawlService(
        validator=RecordingValidator(),
        factory=FakeFactory(MultiItemEngine()),
        extractors=ExtractorRegistry(default=GenericExtractor()),
        repository=InMemoryRepository(),
    )

    result = await service.crawl_site(CrawlRequest(start_url="https://example.com"))

    assert len(result.items) == 2
    assert result.visited_pages == 1
    assert result.succeeded_pages == 1


@pytest.mark.asyncio
async def test_crawl_site_deadline_includes_initial_validation_and_persists_timeout() -> None:
    repository = InMemoryRepository()
    service = CrawlService(
        validator=SlowValidator(),
        factory=FakeFactory(FakeEngine()),
        extractors=ExtractorRegistry(default=GenericExtractor()),
        repository=repository,
    )
    request = CrawlRequest(start_url="https://example.com").model_copy(
        update={"job_timeout_seconds": 0.01}
    )

    with pytest.raises(NavigationError) as caught:
        await service.crawl_site(request)

    assert caught.value.details["reason"] == "job_timeout"
    assert caught.value.job_id is not None
    stored = await repository.get_job(caught.value.job_id)
    assert stored is not None
    assert stored.completed_at is not None
    assert stored.failed_pages == 1
