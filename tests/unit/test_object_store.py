from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from crawling_mcp.adapters.storage.minio_store import MinioObjectStore


class RecordingMinioClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_minio_store_writes_job_scoped_html_with_checksum() -> None:
    client = RecordingMinioClient()
    store = MinioObjectStore(bucket="crawl-data", client=client)
    job_id = uuid4()
    url = "https://news.example.com/article/42"
    html = "<article>기사</article>"

    stored = await store.put_html(job_id, url, html)

    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    assert stored.key == f"jobs/{job_id}/pages/{url_hash}/raw.html"
    assert stored.uri == f"s3://crawl-data/{stored.key}"
    assert stored.sha256 == hashlib.sha256(html.encode("utf-8")).hexdigest()
    assert stored.size_bytes == len(html.encode("utf-8"))
    assert client.calls[0]["bucket_name"] == "crawl-data"
    assert client.calls[0]["object_name"] == stored.key
    assert client.calls[0]["content_type"] == "text/html; charset=utf-8"
