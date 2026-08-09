from __future__ import annotations

import asyncio
import hashlib
import io
from typing import Protocol
from uuid import UUID

from crawling_mcp.ports.object_store import ObjectStore, StoredObject


class MinioClient(Protocol):
    """Subset of the synchronous MinIO SDK used behind the async port."""

    def put_object(self, **kwargs: object) -> object: ...

    def bucket_exists(self, bucket_name: str) -> bool: ...

    def make_bucket(self, bucket_name: str) -> object: ...

    def remove_object(self, bucket_name: str, object_name: str) -> object: ...


class MinioObjectStore(ObjectStore):
    """Store immutable crawl payloads in a MinIO/S3-compatible bucket."""

    def __init__(self, *, bucket: str, client: MinioClient) -> None:
        self._bucket = bucket
        self._client = client
        self._bucket_ready = False
        self._bucket_lock = asyncio.Lock()

    async def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        async with self._bucket_lock:
            if self._bucket_ready:
                return
            exists = await asyncio.to_thread(self._client.bucket_exists, self._bucket)
            if not exists:
                await asyncio.to_thread(self._client.make_bucket, self._bucket)
            self._bucket_ready = True

    async def _put(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        await self._ensure_bucket()
        await asyncio.to_thread(
            self._client.put_object,
            bucket_name=self._bucket,
            object_name=key,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
            metadata={"sha256": digest},
        )
        return StoredObject(
            key=key,
            uri=f"s3://{self._bucket}/{key}",
            sha256=digest,
            size_bytes=len(data),
            content_type=content_type,
        )

    async def put_html(self, job_id: UUID, url: str, html: str) -> StoredObject:
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return await self._put(
            key=f"jobs/{job_id}/pages/{url_hash}/raw.html",
            data=html.encode("utf-8"),
            content_type="text/html; charset=utf-8",
        )

    async def put_artifact(
        self,
        job_id: UUID,
        artifact_id: UUID,
        name: str,
        data: bytes,
        content_type: str,
    ) -> StoredObject:
        safe_name = name.replace("/", "_").replace("\\", "_")
        return await self._put(
            key=f"jobs/{job_id}/failures/{artifact_id}/{safe_name}",
            data=data,
            content_type=content_type,
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self._bucket, key)
