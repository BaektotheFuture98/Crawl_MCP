from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from crawling_mcp.adapters.auth.registry import AuthRegistry
from crawling_mcp.adapters.auth.saved_session import AuthProfileStore
from crawling_mcp.application.auth_service import AuthService
from crawling_mcp.domain.errors import AuthenticationFailedError, AuthenticationRequiredError
from crawling_mcp.domain.models import AuthProfile, Credentials


class FakeContext:
    def __init__(self, loaded_state: Path | None) -> None:
        self.loaded_state = loaded_state

    async def storage_state(self, *, path: Path, indexed_db: bool) -> None:
        await asyncio.to_thread(path.write_text, '{"cookies": []}', encoding="utf-8")


class FakeBrowser:
    def __init__(self) -> None:
        self.loaded_states: list[Path | None] = []

    async def start(self) -> None:
        return None

    @asynccontextmanager
    async def context(self, storage_state: Path | None = None) -> AsyncIterator[Any]:
        self.loaded_states.append(storage_state)
        yield FakeContext(storage_state)

    async def close(self) -> None:
        return None


class FakeAdapter:
    name = "form_login"
    profile_name = "example_login"

    def __init__(self, checks: list[bool]) -> None:
        self.checks = checks
        self.authenticate_calls = 0

    async def is_authenticated(self, context: Any) -> bool:
        return self.checks.pop(0)

    async def authenticate(self, context: Any, credentials: Credentials) -> None:
        assert credentials.username == "user"
        assert credentials.password == "secret"
        self.authenticate_calls += 1


class ConcurrentAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__([])

    async def is_authenticated(self, context: Any) -> bool:
        if context.loaded_state is not None:
            content = context.loaded_state.read_text(encoding="utf-8")
            return content != "expired"
        return self.authenticate_calls > 0

    async def authenticate(self, context: Any, credentials: Credentials) -> None:
        self.authenticate_calls += 1
        await asyncio.sleep(0.05)


class FakeSecrets:
    def credentials(self, username_env: str, password_env: str) -> Credentials:
        return Credentials(username="user", password="secret")


class FailingSecrets:
    def credentials(self, username_env: str, password_env: str) -> Credentials:
        raise AssertionError("valid saved sessions must not resolve login credentials")


def make_service(
    tmp_path: Path,
    adapter: FakeAdapter,
    *,
    secrets: Any | None = None,
    profile_adapter: str = "example_login",
) -> tuple[AuthService, FakeBrowser, Path]:
    auth_root = tmp_path / "data" / "auth"
    state = auth_root / "reader.json"
    profiles = AuthProfileStore(
        {
            "reader": AuthProfile(
                domain="example.com",
                adapter=profile_adapter,
                username_env="USER_ENV",
                password_env="PASSWORD_ENV",
                storage_state_path=str(state),
            )
        }
    )
    registry = AuthRegistry(default=adapter)
    registry.register("example.com", adapter)
    browser = FakeBrowser()
    return (
        AuthService(
            profiles=profiles,
            registry=registry,
            browser=browser,
            auth_root=auth_root,
            secrets=secrets or FakeSecrets(),
        ),
        browser,
        state,
    )


@pytest.mark.asyncio
async def test_auth_service_reuses_valid_saved_state(tmp_path: Path) -> None:
    adapter = FakeAdapter([True])
    service, browser, state = make_service(tmp_path, adapter)
    state.parent.mkdir(parents=True)
    state.write_text("{}", encoding="utf-8")

    async with service.context_for("example.com", "reader") as context:
        assert context.loaded_state == state

    assert browser.loaded_states == [state]
    assert adapter.authenticate_calls == 0


@pytest.mark.asyncio
async def test_auth_service_reuses_valid_state_without_resolving_secrets(tmp_path: Path) -> None:
    adapter = FakeAdapter([True])
    service, _, state = make_service(tmp_path, adapter, secrets=FailingSecrets())
    state.parent.mkdir(parents=True)
    state.write_text("{}", encoding="utf-8")

    async with service.context_for("example.com", "reader") as context:
        assert context.loaded_state == state

    assert adapter.authenticate_calls == 0


@pytest.mark.asyncio
async def test_auth_service_rejects_profile_adapter_mismatch(tmp_path: Path) -> None:
    adapter = FakeAdapter([True])
    service, _, _ = make_service(
        tmp_path,
        adapter,
        profile_adapter="unexpected_adapter",
    )

    with pytest.raises(AuthenticationRequiredError, match="인증"):
        async with service.context_for("example.com", "reader"):
            pass


@pytest.mark.asyncio
async def test_auth_service_reauthenticates_expired_state_and_refreshes_file(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter([False, False, True])
    service, browser, state = make_service(tmp_path, adapter)
    state.parent.mkdir(parents=True)
    state.write_text("expired", encoding="utf-8")

    async with service.context_for("example.com", "reader"):
        pass

    assert browser.loaded_states == [state, state, None]
    assert adapter.authenticate_calls == 1
    assert state.read_text(encoding="utf-8") == '{"cookies": []}'


@pytest.mark.asyncio
async def test_auth_service_rejects_failed_post_login_validation(tmp_path: Path) -> None:
    adapter = FakeAdapter([False])
    service, _, _ = make_service(tmp_path, adapter)

    with pytest.raises(AuthenticationFailedError):
        async with service.context_for("example.com", "reader"):
            pass


@pytest.mark.asyncio
async def test_auth_service_serializes_concurrent_session_refresh(tmp_path: Path) -> None:
    adapter = ConcurrentAdapter()
    service, _, state = make_service(tmp_path, adapter)
    state.parent.mkdir(parents=True)
    state.write_text("expired", encoding="utf-8")

    async def use_context() -> None:
        async with service.context_for("example.com", "reader"):
            pass

    await asyncio.gather(use_context(), use_context())

    assert adapter.authenticate_calls == 1
    assert state.stat().st_mode & 0o777 == 0o600
