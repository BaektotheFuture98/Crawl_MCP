from datetime import UTC, datetime

import pytest

from crawling_mcp.adapters.outbound.extraction.articles.structured import StructuredArticleExtractor
from crawling_mcp.domain.models import PageSnapshot


@pytest.mark.asyncio
async def test_structured_article_extraction_prefers_json_ld_and_canonical_url() -> None:
    html = """
    <html><head>
      <link rel="canonical" href="/news/42?utm_source=test">
      <meta property="og:site_name" content="Fallback Publisher">
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"NewsArticle",
       "headline":"기사 제목","articleBody":"기사 본문입니다.",
       "author":{"@type":"Person","name":"홍길동 기자"},
       "publisher":{"@type":"Organization","name":"동아일보"},
       "datePublished":"2026-08-10T09:30:00+09:00"}
      </script>
    </head><body><article><h1>대체 제목</h1><p>대체 본문</p></article></body></html>
    """

    result = await StructuredArticleExtractor().extract_articles(
        PageSnapshot(url="https://example.com/original", html=html)
    )

    assert len(result) == 1
    assert result[0].url == "https://example.com/news/42"
    assert result[0].title == "기사 제목"
    assert result[0].content == "기사 본문입니다."
    assert result[0].reporter == "홍길동 기자"
    assert result[0].publisher == "동아일보"
    assert result[0].published_at is not None
    assert result[0].published_at.astimezone(UTC) == datetime(2026, 8, 10, 0, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_semantic_article_fallback_and_non_article_rejection() -> None:
    extractor = StructuredArticleExtractor()
    article = await extractor.extract_articles(
        PageSnapshot(
            url="https://example.com/a",
            html="<article><h1>제목</h1><p>첫 문단</p><p>둘째 문단</p></article>",
        )
    )
    listing = await extractor.extract_articles(
        PageSnapshot(url="https://example.com/list", html="<main><a href='/a'>목록</a></main>")
    )

    assert article[0].content == "첫 문단\n둘째 문단"
    assert listing == []
