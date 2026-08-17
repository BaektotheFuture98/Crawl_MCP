from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from crawling_mcp.domain.models import AuthProfile, Credentials


class AuthenticationAdapter(Protocol):
    """Site-specific login and session validation port."""

    @property
    def name(self) -> str: ...

    @property
    def profile_name(self) -> str: ...

    async def is_authenticated(self, context: Any) -> bool: ...

    async def authenticate(self, context: Any, credentials: Credentials) -> None: ...


class AuthProfileProvider(Protocol):
    def get(self, name: str) -> AuthProfile: ...


class AuthenticationResolver(Protocol):
    def get(self, domain: str, *, required: bool) -> AuthenticationAdapter: ...


class SecretProvider(Protocol):
    def credentials(self, username_env: str, password_env: str) -> Credentials: ...


class StoragePathResolver(Protocol):
    def __call__(
        self, auth_root: Path, candidate: Path, *, profile_name: str | None = None
    ) -> Path: ...


class AuthContextProvider(Protocol):
    """Application-facing authenticated browser context provider."""

    def context_for(
        self, domain: str, profile_name: str | None, job_id: UUID | None = None
    ) -> AbstractAsyncContextManager[Any]: ...

    async def validate_session(self, profile_name: str) -> bool: ...
