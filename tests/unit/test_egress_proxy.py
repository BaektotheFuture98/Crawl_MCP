from __future__ import annotations

import asyncio

import pytest

from crawling_mcp.domain.models import ValidatedUrl
from crawling_mcp.infrastructure.egress_proxy import SafeEgressProxy


class UnusedValidator:
    async def validate(self, url: str) -> ValidatedUrl:
        raise AssertionError("not used")


@pytest.mark.asyncio
async def test_egress_connect_uses_one_deadline_for_all_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hanging_connection(
        host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    monkeypatch.setattr(asyncio, "open_connection", hanging_connection)
    proxy = SafeEgressProxy(
        validator=UnusedValidator(),
        connect_timeout_seconds=0.01,
    )
    target = ValidatedUrl(
        url="https://example.com/",
        hostname="example.com",
        port=443,
        addresses=("93.184.216.1", "93.184.216.2", "93.184.216.3"),
    )

    with pytest.raises(TimeoutError):
        await proxy._connect(target)
