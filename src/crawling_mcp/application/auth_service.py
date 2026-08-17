from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog

from crawling_mcp.application.ports.outbound.artifacts import FailureArtifactPort
from crawling_mcp.application.ports.outbound.authentication import (
    AuthenticationAdapter,
    AuthenticationResolver,
    AuthProfileProvider,
    SecretProvider,
    StoragePathResolver,
)
from crawling_mcp.application.ports.outbound.browser import BrowserManagerPort
from crawling_mcp.domain.errors import AuthenticationFailedError, AuthenticationRequiredError
from crawling_mcp.domain.models import AuthProfile, Credentials


class AuthService:
    """Orchestrate saved-session validation and site-specific login."""

    def __init__(
        self,
        *,
        profiles: AuthProfileProvider,
        registry: AuthenticationResolver,
        browser: BrowserManagerPort,
        auth_root: Path,
        secrets: SecretProvider,
        storage_path_resolver: StoragePathResolver,
        artifacts: FailureArtifactPort | None = None,
    ) -> None:
        self._profiles = profiles
        self._registry = registry
        self._browser = browser
        self._auth_root = auth_root
        self._secrets = secrets
        self._storage_path_resolver = storage_path_resolver
        self._artifacts = artifacts
        self._refresh_locks: dict[str, asyncio.Lock] = {}
        self._log = structlog.get_logger(__name__)

    def _profile(self, domain: str, name: str) -> tuple[AuthProfile, AuthenticationAdapter, Path]:
        profile = self._profiles.get(name)
        if profile.domain.lower().rstrip(".") != domain.lower().rstrip("."):
            raise AuthenticationRequiredError(
                profile=name, domain=domain, reason="profile_domain_mismatch"
            )
        adapter = self._registry.get(domain, required=True)
        if profile.adapter != adapter.profile_name:
            raise AuthenticationRequiredError(
                profile=name,
                domain=domain,
                reason="profile_adapter_mismatch",
            )
        storage_path = self._storage_path_resolver(
            self._auth_root,
            Path(profile.storage_state_path),
            profile_name=name,
        )
        return profile, adapter, storage_path

    async def _save_state(self, context: Any, target: Path) -> None:
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            await context.storage_state(path=temporary, indexed_db=True)
            await asyncio.to_thread(os.chmod, temporary, 0o600)
            await asyncio.to_thread(os.replace, temporary, target)
            await asyncio.to_thread(os.chmod, target, 0o600)
        finally:
            await asyncio.to_thread(temporary.unlink, missing_ok=True)

    async def _capture_auth_failure(
        self,
        *,
        job_id: UUID | None,
        error: AuthenticationFailedError,
        context: Any,
        credentials: Credentials,
    ) -> None:
        if self._artifacts is None or job_id is None:
            return
        pages = context.pages
        page = pages[-1] if pages else None
        try:
            await self._artifacts.capture(
                job_id,
                error,
                page=page,
                sensitive_values=(credentials.username, credentials.password),
            )
        except Exception as artifact_error:
            self._log.error(
                "auth_artifact_capture_failed",
                job_id=str(job_id),
                error_type=type(artifact_error).__name__,
            )

    @asynccontextmanager
    async def context_for(
        self, domain: str, profile_name: str | None, job_id: UUID | None = None
    ) -> AsyncIterator[Any]:
        """Yield a public, saved-session, or freshly authenticated context."""
        if profile_name is None:
            async with self._browser.context() as public_context:
                yield public_context
            return
        profile, adapter, storage_path = self._profile(domain, profile_name)
        if await asyncio.to_thread(storage_path.is_file):
            async with self._browser.context(storage_path) as saved_context:
                if await adapter.is_authenticated(saved_context):
                    yield saved_context
                    return
        refresh_stack = AsyncExitStack()
        context: Any | None = None
        lock = self._refresh_locks.setdefault(profile_name, asyncio.Lock())
        try:
            async with lock:
                if await asyncio.to_thread(storage_path.is_file):
                    saved = await refresh_stack.enter_async_context(
                        self._browser.context(storage_path)
                    )
                    if await adapter.is_authenticated(saved):
                        context = saved
                    else:
                        await refresh_stack.aclose()
                        refresh_stack = AsyncExitStack()
                if context is None:
                    credentials = self._secrets.credentials(
                        profile.username_env, profile.password_env
                    )
                    fresh_context = await refresh_stack.enter_async_context(self._browser.context())
                    try:
                        await adapter.authenticate(fresh_context, credentials)
                    except AuthenticationFailedError as error:
                        await self._capture_auth_failure(
                            job_id=job_id,
                            error=error,
                            context=fresh_context,
                            credentials=credentials,
                        )
                        raise
                    if not await adapter.is_authenticated(fresh_context):
                        validation_error = AuthenticationFailedError(
                            domain=domain, reason="post_login_check_failed"
                        )
                        await self._capture_auth_failure(
                            job_id=job_id,
                            error=validation_error,
                            context=fresh_context,
                            credentials=credentials,
                        )
                        raise validation_error
                    await self._save_state(fresh_context, storage_path)
                    context = fresh_context
            if context is None:
                raise AuthenticationFailedError(domain=domain, reason="context_not_created")
            yield context
        finally:
            await refresh_stack.aclose()

    async def validate_session(self, profile_name: str) -> bool:
        """Check a stored state without performing login."""
        profile = self._profiles.get(profile_name)
        _, adapter, storage_path = self._profile(profile.domain, profile_name)
        if not await asyncio.to_thread(storage_path.is_file):
            return False
        async with self._browser.context(storage_path) as context:
            return await adapter.is_authenticated(context)
