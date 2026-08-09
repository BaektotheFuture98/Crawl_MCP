from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Immutable object metadata retained by relational storage."""

    key: str
    uri: str
    sha256: str
    size_bytes: int
    content_type: str


class ObjectStore(Protocol):
    """Asynchronous object-store boundary for crawl payloads and diagnostics."""

    async def put_html(self, job_id: UUID, url: str, html: str) -> StoredObject: ...

    async def put_artifact(
        self,
        job_id: UUID,
        artifact_id: UUID,
        name: str,
        data: bytes,
        content_type: str,
    ) -> StoredObject: ...

    async def delete(self, key: str) -> None: ...
