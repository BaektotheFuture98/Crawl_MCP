from __future__ import annotations

from typing import Any, cast

import pytest

from crawling_mcp.bootstrap import ApplicationContainer
from crawling_mcp.domain.enums import ErrorCode
from crawling_mcp.server import create_server


class UnusedContainer:
    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def crawl_site(self, request: Any) -> Any:
        raise AssertionError("invalid transport input must not reach the application")


@pytest.mark.asyncio
async def test_server_registers_public_tools() -> None:
    server = create_server()

    tools = await server.list_tools()

    assert {tool.name for tool in tools} == {
        "configure_crawl_target",
        "crawl_site",
        "get_article",
        "get_crawl_status",
        "get_recent_article_changes",
        "list_crawl_targets",
        "list_supported_sites",
        "run_crawl_target",
        "scrape_page",
        "validate_session",
    }


@pytest.mark.asyncio
async def test_server_returns_structured_error_for_transport_type_validation() -> None:
    server = create_server(container=cast(ApplicationContainer, UnusedContainer()))

    result = await server.call_tool(
        "crawl_site",
        {"start_url": "https://example.com", "max_pages": "not-an-integer"},
    )

    assert isinstance(result, tuple)
    assert result[1]["error_code"] == ErrorCode.CRAWL_LIMIT_EXCEEDED
