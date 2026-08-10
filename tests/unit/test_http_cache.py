from __future__ import annotations

from crawling_mcp.adapters.crawlee.http_engine import HttpCrawlerEngine
from crawling_mcp.adapters.extractors.generic import GenericExtractor
from crawling_mcp.adapters.extractors.registry import ExtractorRegistry
from crawling_mcp.domain.models import CrawlCacheEntry, CrawlContext, ValidatedUrl


class Validator:
    async def validate(self, url: str) -> ValidatedUrl:
        return ValidatedUrl(url=url, hostname="example.com", port=443, addresses=("1.1.1.1",))


def engine() -> HttpCrawlerEngine:
    return HttpCrawlerEngine(
        validator=Validator(),
        extractors=ExtractorRegistry(default=GenericExtractor()),
    )


def test_conditional_request_uses_previous_etag_and_last_modified() -> None:
    context = CrawlContext(
        domain="example.com",
        cache_entries={
            "https://example.com/a": CrawlCacheEntry(
                url="https://example.com/a",
                etag='"v1"',
                last_modified="Mon, 10 Aug 2026 01:00:00 GMT",
                depth=1,
            )
        },
    )

    request = engine()._request("https://example.com/a", label="DETAIL", depth=1, context=context)

    assert request.headers.get("If-None-Match") == '"v1"'
    assert request.headers.get("If-Modified-Since") == "Mon, 10 Aug 2026 01:00:00 GMT"
    assert request.user_data["depth"] == 1


def test_request_without_cached_validators_has_no_conditional_headers() -> None:
    request = engine()._request(
        "https://example.com/a",
        label="DETAIL",
        depth=0,
        context=CrawlContext(domain="example.com"),
    )

    assert "If-None-Match" not in request.headers
    assert "If-Modified-Since" not in request.headers


def test_conditional_cache_lookup_normalizes_equivalent_urls() -> None:
    context = CrawlContext(
        domain="example.com",
        cache_entries={
            "https://example.com/": CrawlCacheEntry(url="https://example.com/", etag='"normalized"')
        },
    )

    request = engine()._request("https://example.com", label="START", depth=0, context=context)

    assert request.headers.get("If-None-Match") == '"normalized"'
