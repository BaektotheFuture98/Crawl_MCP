from __future__ import annotations

from typing import Any

import pytest

from crawling_mcp.adapters.outbound.authentication.no_auth import NoAuthAdapter
from crawling_mcp.adapters.outbound.authentication.registry import AuthRegistry
from crawling_mcp.domain.errors import UnsupportedSiteError


def test_auth_registry_resolves_registered_adapter_and_public_fallback() -> None:
    registry = AuthRegistry(default=NoAuthAdapter())
    registered = NoAuthAdapter(name="form_login")
    registry.register("example.com", registered)

    assert registry.get("example.com", required=True) is registered
    assert registry.get("public.example", required=False).name == "no_auth"
    with pytest.raises(UnsupportedSiteError):
        registry.get("unknown.example", required=True)


@pytest.mark.asyncio
async def test_no_auth_adapter_is_always_authenticated() -> None:
    assert await NoAuthAdapter().is_authenticated(context=Any) is True
