from __future__ import annotations

from typing import Any, Protocol

from crawling_mcp.domain.models import Credentials


class AuthenticationAdapter(Protocol):
    """Site-specific login and session validation port."""

    @property
    def name(self) -> str: ...

    async def is_authenticated(self, context: Any) -> bool: ...

    async def authenticate(self, context: Any, credentials: Credentials) -> None: ...
