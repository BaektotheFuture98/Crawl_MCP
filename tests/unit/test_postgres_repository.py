from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from crawling_mcp.adapters.storage.postgres_repository import PostgresRepository
from crawling_mcp.domain.models import PageItem
from crawling_mcp.ports.object_store import StoredObject


def test_postgres_repository_builds_append_only_article_values() -> None:
    job_id = uuid4()
    item = PageItem(
        url="https://news.example.com/article/42",
        title="기사 제목",
        content="기사 본문",
        source="동아일보",
        published_at=datetime(2026, 8, 10, 0, 30, tzinfo=UTC),
        metadata={"section": "정치"},
    )
    raw_html = StoredObject(
        key=f"jobs/{job_id}/pages/hash/raw.html",
        uri=f"s3://crawl-data/jobs/{job_id}/pages/hash/raw.html",
        sha256="a" * 64,
        size_bytes=123,
        content_type="text/html; charset=utf-8",
    )

    values = PostgresRepository.article_values(job_id, item, raw_html)

    assert values["crawl_job_id"] == job_id
    assert values["url"] == item.url
    assert values["title"] == "기사 제목"
    assert values["content"] == "기사 본문"
    assert values["source"] == "동아일보"
    assert values["published_at"] == item.published_at
    assert values["metadata"] == {"section": "정치"}
    assert values["raw_html_key"] == raw_html.key
    assert values["raw_html_sha256"] == raw_html.sha256
