from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from crawling_mcp.domain.errors import BlockedUrlError, InvalidUrlError
from crawling_mcp.infrastructure.security import UrlSecurityValidator


class StaticResolver:
    def __init__(self, addresses: Sequence[str]) -> None:
        self.addresses = addresses

    async def resolve(self, hostname: str, port: int) -> Sequence[str]:
        return self.addresses


class SlowResolver:
    async def resolve(self, hostname: str, port: int) -> Sequence[str]:
        await asyncio.sleep(1)
        return ["93.184.216.34"]


@pytest.mark.asyncio
async def test_security_accepts_url_only_when_all_answers_are_public() -> None:
    validator = UrlSecurityValidator(resolver=StaticResolver(["93.184.216.34"]))

    result = await validator.validate("https://example.com/path")

    assert result.url == "https://example.com/path"
    assert result.hostname == "example.com"
    assert result.addresses == ("93.184.216.34",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1"],
)
async def test_security_blocks_non_public_addresses(address: str) -> None:
    validator = UrlSecurityValidator(resolver=StaticResolver([address]))

    with pytest.raises(BlockedUrlError):
        await validator.validate("https://example.com")


@pytest.mark.asyncio
async def test_security_blocks_mixed_public_and_private_dns_answers() -> None:
    validator = UrlSecurityValidator(resolver=StaticResolver(["93.184.216.34", "10.0.0.1"]))

    with pytest.raises(BlockedUrlError):
        await validator.validate("https://example.com")


@pytest.mark.asyncio
async def test_security_rejects_host_outside_allowlist() -> None:
    validator = UrlSecurityValidator(
        resolver=StaticResolver(["93.184.216.34"]), domain_allowlist=("allowed.example",)
    )

    with pytest.raises(BlockedUrlError):
        await validator.validate("https://example.com")


@pytest.mark.asyncio
async def test_security_allows_private_address_only_in_explicit_test_mode() -> None:
    validator = UrlSecurityValidator(
        resolver=StaticResolver(["127.0.0.1"]), allow_private_networks=True
    )

    result = await validator.validate("http://127.0.0.1:8000/test-site/list")

    assert result.addresses == ("127.0.0.1",)


@pytest.mark.asyncio
async def test_security_rejects_url_credentials() -> None:
    validator = UrlSecurityValidator(resolver=StaticResolver(["93.184.216.34"]))

    with pytest.raises(InvalidUrlError):
        await validator.validate("https://user:password@example.com")


@pytest.mark.asyncio
async def test_security_bounds_dns_resolution_time() -> None:
    validator = UrlSecurityValidator(resolver=SlowResolver(), resolver_timeout_seconds=0.01)

    with pytest.raises(InvalidUrlError) as caught:
        await validator.validate("https://example.com")

    assert caught.value.details["reason"] == "dns_resolution_timeout"
