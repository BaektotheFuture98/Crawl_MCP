from __future__ import annotations

from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from crawling_mcp.adapters.mcp.tools import register_tools
from crawling_mcp.domain.enums import ErrorCode
from crawling_mcp.domain.errors import BlockedUrlError
from crawling_mcp.domain.models import PageItem, SupportedSite


class FakeContainer:
    async def scrape_page(self, request: Any) -> PageItem:
        if "blocked" in request.url:
            raise BlockedUrlError(domain="blocked.example", address="127.0.0.1", password="secret")
        return PageItem(url=request.url, title="Title", content="Body")

    async def crawl_site(self, request: Any) -> Any:
        raise AssertionError("not used")

    async def validate_session(self, auth_profile: str) -> bool:
        return auth_profile == "valid"

    def list_supported_sites(self) -> list[SupportedSite]:
        return [
            SupportedSite(domain="example.com", authentication="form_login", extractor="example")
        ]


def structured(result: Any) -> dict[str, Any]:
    assert isinstance(result, tuple)
    assert isinstance(result[1], dict)
    return result[1]


@pytest.mark.asyncio
async def test_mcp_tool_returns_page_payload() -> None:
    server = FastMCP("test")
    register_tools(server, FakeContainer())

    result = structured(
        await server.call_tool(
            "scrape_page", {"url": "https://example.com/page", "crawl_mode": "auto"}
        )
    )

    assert result["url"] == "https://example.com/page"
    assert result["title"] == "Title"
    assert result["content"] == "Body"


@pytest.mark.asyncio
async def test_mcp_tool_maps_domain_error_without_traceback() -> None:
    server = FastMCP("test")
    register_tools(server, FakeContainer())

    result = structured(
        await server.call_tool(
            "scrape_page", {"url": "https://blocked.example", "crawl_mode": "auto"}
        )
    )

    assert result["error_code"] == ErrorCode.BLOCKED_URL
    assert "traceback" not in str(result).lower()
    assert result["details"] == {
        "domain": "blocked.example",
        "address": "127.0.0.1",
        "password": "***REDACTED***",
    }


@pytest.mark.asyncio
async def test_mcp_tool_lists_supported_sites_and_validates_session() -> None:
    server = FastMCP("test")
    register_tools(server, FakeContainer())

    sites = structured(await server.call_tool("list_supported_sites", {}))
    session = structured(await server.call_tool("validate_session", {"auth_profile": "valid"}))

    assert sites == {
        "sites": [{"domain": "example.com", "authentication": "form_login", "extractor": "example"}]
    }
    assert session == {"auth_profile": "valid", "valid": True}
