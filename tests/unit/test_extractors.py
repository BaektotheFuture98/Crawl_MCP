from __future__ import annotations

import pytest

from crawling_mcp.adapters.extractors.generic import GenericExtractor
from crawling_mcp.adapters.extractors.registry import ExtractorRegistry
from crawling_mcp.domain.errors import UnsupportedSiteError
from crawling_mcp.domain.models import PageSnapshot


@pytest.mark.asyncio
async def test_generic_extractor_removes_chrome_and_extracts_metadata() -> None:
    snapshot = PageSnapshot(
        url="https://example.com/final",
        status_code=200,
        html="""
        <html lang="ko"><head><title> 문서 제목 </title>
        <meta name="description" content="설명"><link rel="canonical" href="/canonical">
        <style>.hidden{}</style><script>secret()</script></head>
        <body><nav>메뉴</nav><main><h1>제목</h1><p>본문 문장</p></main>
        <footer>꼬리말</footer></body></html>
        """,
    )

    items = await GenericExtractor().extract(snapshot)

    assert len(items) == 1
    item = items[0]
    assert item.title == "문서 제목"
    assert item.content == "제목 본문 문장"
    assert item.meta_description == "설명"
    assert item.canonical_url == "https://example.com/canonical"
    assert item.language == "ko"
    assert item.http_status_code == 200
    assert "secret" not in item.content
    assert "메뉴" not in item.content


def test_extractor_registry_uses_exact_registration_and_public_fallback() -> None:
    registry = ExtractorRegistry(default=GenericExtractor())
    example = GenericExtractor(name="example")
    registry.register("example.com", example)

    assert registry.get("example.com", authenticated=False) is example
    assert registry.get("public.example", authenticated=False).name == "generic"
    with pytest.raises(UnsupportedSiteError):
        registry.get("unknown.example", authenticated=True)


def test_extractor_registry_returns_secret_free_metadata_snapshot() -> None:
    registry = ExtractorRegistry(default=GenericExtractor())
    registry.register("example.com", GenericExtractor(name="example"))

    assert registry.metadata() == {"example.com": "example"}
