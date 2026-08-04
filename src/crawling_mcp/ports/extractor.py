from __future__ import annotations

from typing import Protocol

from crawling_mcp.domain.models import PageItem, PageSnapshot


class PageExtractor(Protocol):
    """Extract structured items from an engine-neutral snapshot."""

    @property
    def name(self) -> str: ...

    async def extract(self, snapshot: PageSnapshot) -> list[PageItem]: ...


class ExtractorResolver(Protocol):
    """Resolve the extractor registered for a domain."""

    def get(self, domain: str, *, authenticated: bool) -> PageExtractor: ...
