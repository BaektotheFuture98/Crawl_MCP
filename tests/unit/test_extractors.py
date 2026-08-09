from __future__ import annotations

from datetime import UTC, datetime

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


@pytest.mark.asyncio
async def test_generic_extractor_extracts_article_metadata_from_json_ld() -> None:
    snapshot = PageSnapshot(
        url="https://news.example.com/article/1",
        status_code=200,
        html="""
        <html><head>
        <title>문서 제목</title>
        <meta property="article:published_time" content="2026-08-09T10:00:00+09:00">
        <meta property="og:site_name" content="대체 출처">
        <script type="application/ld+json">
        {"@type":"NewsArticle","datePublished":"2026-08-10T09:30:00+09:00",
         "publisher":{"name":"동아일보"}, "author":{"name":"홍길동 기자"}}
        </script>
        </head><body><article><p>기사 본문입니다.</p></article></body></html>
        """,
    )

    item = (await GenericExtractor().extract(snapshot))[0]

    assert item.published_at == datetime(2026, 8, 10, 0, 30, tzinfo=UTC)
    assert item.publisher == "동아일보"
    assert item.reporter == "홍길동 기자"
    assert item.content == "기사 본문입니다."
    assert "raw_html" not in type(item).model_fields


@pytest.mark.asyncio
async def test_generic_extractor_leaves_article_metadata_null_when_missing() -> None:
    snapshot = PageSnapshot(
        url="https://example.com/plain",
        html="<html><head><title>문서</title></head><body><main>본문</main></body></html>",
    )

    item = (await GenericExtractor().extract(snapshot))[0]

    assert item.published_at is None
    assert item.publisher is None
    assert item.reporter is None


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
