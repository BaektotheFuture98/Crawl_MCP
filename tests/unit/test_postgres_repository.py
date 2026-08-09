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
        publisher="동아일보",
        reporter="홍길동 기자",
        meta_description="요약 설명",
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

    values = PostgresRepository.article_values(item)

    assert "id" not in values
    assert "crawl_job_id" not in values
    assert values["url"] == item.url
    assert values["ar_title"] == "기사 제목"
    assert values["ar_content"] == "기사 본문"
    assert values["publisher"] == "동아일보"
    assert values["reporter"] == "홍길동 기자"
    assert values["published_at"] == datetime(2026, 8, 10, 9, 30)

    article_id = uuid4()
    object_values = PostgresRepository.article_object_values(job_id, article_id, item, raw_html)
    assert object_values["article_id"] == article_id
    assert object_values["crawl_job_id"] == job_id
    assert object_values["meta_description"] == "요약 설명"
    assert object_values["metadata"] == {"section": "정치"}
    assert object_values["raw_html_key"] == raw_html.key
    assert object_values["raw_html_sha256"] == raw_html.sha256
