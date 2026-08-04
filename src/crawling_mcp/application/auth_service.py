from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

from playwright.async_api import BrowserContext

from crawling_mcp.adapters.auth.registry import AuthRegistry
from crawling_mcp.adapters.auth.saved_session import AuthProfileStore, resolve_storage_path
from crawling_mcp.domain.errors import AuthenticationFailedError, AuthenticationRequiredError
from crawling_mcp.domain.models import Credentials
from crawling_mcp.ports.authentication import AuthenticationAdapter
from crawling_mcp.ports.browser import BrowserManagerPort


class SecretProvider(Protocol):
    """Resolve credentials without receiving them through MCP input."""

    def credentials(self, username_env: str, password_env: str) -> Credentials: ...


class EnvironmentSecretProvider:
    """Read site credentials from process environment variables."""

    def credentials(self, username_env: str, password_env: str) -> Credentials:
        """Resolve both configured environment variables."""
        username = os.getenv(username_env)
        password = os.getenv(password_env)
        if not username or not password:
            raise AuthenticationRequiredError(reason="credential_environment_missing")
        return Credentials(username=username, password=password)


class AuthService:
    """Orchestrate saved-session validation and site-specific login."""

    def __init__(
        self,
        *,
        profiles: AuthProfileStore,
        registry: AuthRegistry,
        browser: BrowserManagerPort,
        auth_root: Path,
        secrets: SecretProvider | None = None,
    ) -> None:
        self._profiles = profiles
        self._registry = registry
        self._browser = browser
        self._auth_root = auth_root
        self._secrets = secrets or EnvironmentSecretProvider()

    def _profile(self, domain: str, name: str) -> tuple[AuthenticationAdapter, Path, Credentials]:
        profile = self._profiles.get(name)
        if profile.domain.lower().rstrip(".") != domain.lower().rstrip("."):
            raise AuthenticationRequiredError(
                profile=name, domain=domain, reason="profile_domain_mismatch"
            )
        adapter = self._registry.get(domain, required=True)
        storage_path = resolve_storage_path(self._auth_root, Path(profile.storage_state_path))
        credentials = self._secrets.credentials(profile.username_env, profile.password_env)
        return adapter, storage_path, credentials

    async def _save_state(self, context: BrowserContext, target: Path) -> None:
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.stem}.tmp.json")
        await context.storage_state(path=temporary, indexed_db=True)
        await asyncio.to_thread(os.replace, temporary, target)

    @asynccontextmanager
    async def context_for(
        self, domain: str, profile_name: str | None
    ) -> AsyncIterator[BrowserContext]:
        """Yield a public, saved-session, or freshly authenticated context."""
        if profile_name is None:
            async with self._browser.context() as context:
                yield context
            return
        adapter, storage_path, credentials = self._profile(domain, profile_name)
        if await asyncio.to_thread(storage_path.is_file):
            async with self._browser.context(storage_path) as context:
                if await adapter.is_authenticated(context):
                    yield context
                    return
        async with self._browser.context() as context:
            await adapter.authenticate(context, credentials)
            if not await adapter.is_authenticated(context):
                raise AuthenticationFailedError(domain=domain, reason="post_login_check_failed")
            await self._save_state(context, storage_path)
            yield context

    async def validate_session(self, profile_name: str) -> bool:
        """Check a stored state without performing login."""
        profile = self._profiles.get(profile_name)
        adapter = self._registry.get(profile.domain, required=True)
        storage_path = resolve_storage_path(self._auth_root, Path(profile.storage_state_path))
        if not await asyncio.to_thread(storage_path.is_file):
            return False
        async with self._browser.context(storage_path) as context:
            return await adapter.is_authenticated(context)
