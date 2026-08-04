from __future__ import annotations

from typing import Any

import pytest

from crawling_mcp.domain.errors import NavigationError
from crawling_mcp.domain.models import ValidatedUrl
from crawling_mcp.infrastructure.robots import RobotsTxtChecker


class AllowValidator:
    async def validate(self, url: str) -> ValidatedUrl:
        return ValidatedUrl(
            url=url,
            hostname="example.com",
            port=443,
            addresses=("93.184.216.34",),
        )


class FakeResponse:
    status_code = 503
    text = ""
    url = "https://example.com/robots.txt"


class FakeClient:
    def __init__(self, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def get(self, url: str) -> FakeResponse:
        return FakeResponse()


@pytest.mark.asyncio
async def test_robots_checker_fails_closed_on_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("crawling_mcp.infrastructure.robots.httpx.AsyncClient", FakeClient)
    checker = RobotsTxtChecker(validator=AllowValidator())

    with pytest.raises(NavigationError) as caught:
        await checker.allowed("https://example.com/private")

    assert caught.value.details["reason"] == "robots_unavailable"
