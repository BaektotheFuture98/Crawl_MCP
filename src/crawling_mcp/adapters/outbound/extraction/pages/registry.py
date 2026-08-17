from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from crawling_mcp.application.ports.outbound.extractor import PageExtractor
from crawling_mcp.domain.errors import UnsupportedSiteError


class ExtractorRegistry:
    """Domain-to-extractor registry with a public-page fallback."""

    def __init__(self, *, default: PageExtractor) -> None:
        self._default = default
        self._extractors: dict[str, PageExtractor] = {}

    def register(self, domain: str, extractor: PageExtractor) -> None:
        """Register an exact normalized domain."""
        self._extractors[domain.lower().rstrip(".")] = extractor

    def get(self, domain: str, *, authenticated: bool) -> PageExtractor:
        """Resolve an extractor or the safe public fallback."""
        normalized = domain.lower().rstrip(".")
        extractor = self._extractors.get(normalized)
        if extractor is not None:
            return extractor
        if authenticated:
            raise UnsupportedSiteError(domain=normalized)
        return self._default

    def metadata(self) -> Mapping[str, str]:
        """Return an immutable, secret-free registry snapshot."""
        return MappingProxyType(
            {domain: extractor.name for domain, extractor in sorted(self._extractors.items())}
        )
