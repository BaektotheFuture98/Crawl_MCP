from __future__ import annotations

from typing import Any

from crawling_mcp.domain.models import Credentials


class NoAuthAdapter:
    """Authentication strategy for public pages."""

    def __init__(self, name: str = "no_auth") -> None:
        self._name = name

    @property
    def name(self) -> str:
        """Return public adapter metadata name."""
        return self._name

    async def is_authenticated(self, context: Any) -> bool:
        """Public pages are always considered authenticated."""
        return True

    async def authenticate(self, context: Any, credentials: Credentials) -> None:
        """No login action is required for public pages."""
