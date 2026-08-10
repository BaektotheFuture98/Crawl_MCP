from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from crawling_mcp.ports.extractor import ArticleExtractor


class ArticleExtractorRegistry:
    """Exact-domain article adapters with a structured public fallback."""

    def __init__(self, *, default: ArticleExtractor) -> None:
        self._default = default
        self._extractors: dict[str, ArticleExtractor] = {}

    def register(self, domain: str, extractor: ArticleExtractor) -> None:
        self._extractors[domain.lower().rstrip(".")] = extractor

    def get(self, domain: str) -> ArticleExtractor:
        return self._extractors.get(domain.lower().rstrip("."), self._default)

    def metadata(self) -> Mapping[str, str]:
        return MappingProxyType(
            {domain: extractor.name for domain, extractor in sorted(self._extractors.items())}
        )
