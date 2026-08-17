from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from crawling_mcp.application.ports.outbound.authentication import AuthenticationAdapter
from crawling_mcp.domain.errors import UnsupportedSiteError


class AuthRegistry:
    """Exact-domain authentication adapter registry."""

    def __init__(self, *, default: AuthenticationAdapter) -> None:
        self._default = default
        self._adapters: dict[str, AuthenticationAdapter] = {}

    def register(self, domain: str, adapter: AuthenticationAdapter) -> None:
        """Register a site adapter by normalized exact domain."""
        self._adapters[domain.lower().rstrip(".")] = adapter

    def get(self, domain: str, *, required: bool) -> AuthenticationAdapter:
        """Resolve an adapter or the public fallback."""
        normalized = domain.lower().rstrip(".")
        adapter = self._adapters.get(normalized)
        if adapter is not None:
            return adapter
        if required:
            raise UnsupportedSiteError(domain=normalized)
        return self._default

    def metadata(self) -> Mapping[str, str]:
        """Return immutable adapter names without credentials."""
        return MappingProxyType(
            {domain: adapter.name for domain, adapter in sorted(self._adapters.items())}
        )
