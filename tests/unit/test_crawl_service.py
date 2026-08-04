from __future__ import annotations

import pytest

from crawling_mcp.adapters.extractors.generic import GenericExtractor
from crawling_mcp.adapters.extractors.registry import ExtractorRegistry
from crawling_mcp.adapters.storage.memory_repository import InMemoryRepository
from crawling_mcp.application.crawl_service import CrawlService
from crawling_mcp.domain.enums import CrawlMode
from crawling_mcp.domain.models import (
    CrawlContext,
    CrawlRequest,
    CrawlResult,
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


class FakeEngine:
    async def scrape(self, request: ScrapePageRequest, context: CrawlContext) -> PageSnapshot:
        return PageSnapshot(
            url="https://example.com/final",
            status_code=200,
            html="<html><title>Example</title><body><main>Hello</main></body></html>",
        )

    async def crawl(self, request: CrawlRequest, context: CrawlContext) -> CrawlResult:
        return CrawlResult(start_url=request.start_url)


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
