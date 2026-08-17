from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol
from urllib.parse import urlsplit

from crawling_mcp.domain.enums import PageType
from crawling_mcp.domain.models import PageSnapshot


class PageNavigationAdapter(Protocol):
    """Site-specific page classification and link-discovery strategy."""

    @property
    def name(self) -> str: ...

    def classify(self, snapshot: PageSnapshot) -> PageType: ...

    def links(self, snapshot: PageSnapshot) -> list[str]: ...


class GenericNavigationAdapter:
    """Conservative public-site navigation heuristics."""

    name = "generic"

    def classify(self, snapshot: PageSnapshot) -> PageType:
        """Classify common root, list and detail URL shapes."""
        if snapshot.page_type is not PageType.DETAIL:
            return snapshot.page_type
        path = urlsplit(snapshot.url).path.rstrip("/")
        if path in {"", "/"}:
            return PageType.START
        lowered = path.lower()
        if any(part in lowered for part in ("/list", "/products", "/search", "/category")):
            return PageType.LIST
        return PageType.DETAIL

    def links(self, snapshot: PageSnapshot) -> list[str]:
        """Return all links for subsequent global policy filtering."""
        return list(snapshot.links)


class ExampleNavigationAdapter(GenericNavigationAdapter):
    """Explicit page and link rules for the local development site."""

    name = "example"

    def classify(self, snapshot: PageSnapshot) -> PageType:
        """Classify the local login, list and detail routes."""
        path = urlsplit(snapshot.url).path.rstrip("/")
        if path in {"/test-site/login", ""}:
            return PageType.START
        if path in {"/test-site/list", "/test-site/concurrency-list"}:
            return PageType.LIST
        return PageType.DETAIL

    def links(self, snapshot: PageSnapshot) -> list[str]:
        """Follow only routes owned by the local test site."""
        return [link for link in snapshot.links if urlsplit(link).path.startswith("/test-site/")]


class NavigationRegistry:
    """Exact-domain registry for page navigation strategies."""

    def __init__(self, *, default: PageNavigationAdapter | None = None) -> None:
        self._default = default or GenericNavigationAdapter()
        self._adapters: dict[str, PageNavigationAdapter] = {}

    def register(self, domain: str, adapter: PageNavigationAdapter) -> None:
        """Register one explicit site navigation strategy."""
        self._adapters[domain.lower().rstrip(".")] = adapter

    def get(self, domain: str | None) -> PageNavigationAdapter:
        """Resolve an exact-domain adapter or the generic fallback."""
        if domain is None:
            return self._default
        return self._adapters.get(domain.lower().rstrip("."), self._default)

    def metadata(self) -> Mapping[str, str]:
        """Return an immutable registry snapshot."""
        return MappingProxyType(
            {domain: adapter.name for domain, adapter in sorted(self._adapters.items())}
        )


class PageRouter:
    """Route page classification and link discovery through site adapters."""

    def __init__(self, *, registry: NavigationRegistry | None = None) -> None:
        self._registry = registry or NavigationRegistry()

    def classify(self, snapshot: PageSnapshot, *, domain: str | None = None) -> PageType:
        """Classify a page with its registered site strategy."""
        return self._registry.get(domain).classify(snapshot)

    def links(self, snapshot: PageSnapshot, *, domain: str | None = None) -> list[str]:
        """Discover candidate links with its registered site strategy."""
        return self._registry.get(domain).links(snapshot)
