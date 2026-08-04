from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol
from uuid import UUID

from crawling_mcp.domain.models import Credentials


class AuthenticationAdapter(Protocol):
    """Site-specific login and session validation port."""

    @property
    def name(self) -> str: ...

    @property
    def profile_name(self) -> str: ...

    async def is_authenticated(self, context: Any) -> bool: ...

    async def authenticate(self, context: Any, credentials: Credentials) -> None: ...


class AuthContextProvider(Protocol):
    """Application-facing authenticated browser context provider."""

    def context_for(
        self, domain: str, profile_name: str | None, job_id: UUID | None = None
    ) -> AbstractAsyncContextManager[Any]: ...

    async def validate_session(self, profile_name: str) -> bool: ...
