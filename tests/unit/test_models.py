from __future__ import annotations

import pytest
from pydantic import ValidationError

from crawling_mcp.domain.enums import CrawlMode
from crawling_mcp.domain.models import CrawlRequest


def test_crawl_request_uses_conservative_defaults() -> None:
    request = CrawlRequest(start_url="https://example.com")

    assert request.crawl_mode is CrawlMode.AUTO
    assert request.max_pages == 20
    assert request.max_depth == 2
    assert request.max_request_retries == 2
    assert request.request_timeout_seconds == 30
    assert request.max_concurrency == 3
    assert request.same_domain_only is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_pages", 0),
        ("max_pages", 501),
        ("max_depth", -1),
        ("max_depth", 11),
        ("max_concurrency", 0),
        ("request_timeout_seconds", 0),
    ],
)
def test_crawl_request_rejects_unsafe_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        CrawlRequest(start_url="https://example.com", **{field: value})


def test_crawl_request_does_not_share_pattern_lists() -> None:
    first = CrawlRequest(start_url="https://example.com")
    second = CrawlRequest(start_url="https://example.com")

    first.include_patterns.append("/docs/*")

    assert second.include_patterns == []
