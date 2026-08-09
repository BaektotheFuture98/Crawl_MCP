from __future__ import annotations

from uuid import uuid4

import pytest

from crawling_mcp.adapters.storage.minio_store import MinioObjectStore


class RecordingMinioClient:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def bucket_exists(self, bucket_name: str) -> bool:
        return True

    def make_bucket(self, bucket_name: str) -> object:
        raise AssertionError("existing bucket must not be recreated")

    def put_object(self, **kwargs: object) -> object:
        self.keys.append(str(kwargs["object_name"]))
        return object()

    def remove_object(self, bucket_name: str, object_name: str) -> object:
        return object()


@pytest.mark.asyncio
async def test_raw_html_versions_for_same_url_use_immutable_content_keys() -> None:
    client = RecordingMinioClient()
    store = MinioObjectStore(bucket="crawl-data", client=client)
    job_id = uuid4()

    first = await store.put_html(job_id, "https://example.com/article", "first")
    second = await store.put_html(job_id, "https://example.com/article", "second")
    repeated = await store.put_html(job_id, "https://example.com/article", "first")

    assert first.key != second.key
    assert first.key != repeated.key
    assert first.sha256 in first.key
    assert second.sha256 in second.key
    assert client.keys == [first.key, second.key, repeated.key]
