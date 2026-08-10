from __future__ import annotations

from typing import Protocol

from crawling_mcp.domain.articles import ArticleCandidate
from crawling_mcp.domain.models import PageItem, PageSnapshot


class PageExtractor(Protocol):
    """Extract structured items from an engine-neutral snapshot."""

    @property
    def name(self) -> str: ...

    async def extract(self, snapshot: PageSnapshot) -> list[PageItem]: ...


class ExtractorResolver(Protocol):
    """Resolve the extractor registered for a domain."""

    def get(self, domain: str, *, authenticated: bool) -> PageExtractor: ...


class ArticleExtractor(Protocol):
    """Interpret an engine-neutral page as zero or more articles."""

    @property
    def name(self) -> str: ...

    async def extract_articles(self, snapshot: PageSnapshot) -> list[ArticleCandidate]: ...


class ArticleExtractorResolver(Protocol):
    """Resolve an article adapter for an exact domain or structured fallback."""

    def get(self, domain: str) -> ArticleExtractor: ...
