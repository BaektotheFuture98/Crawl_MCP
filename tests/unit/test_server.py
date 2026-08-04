from __future__ import annotations

import pytest

from crawling_mcp.server import create_server


@pytest.mark.asyncio
async def test_server_registers_public_tools() -> None:
    server = create_server()

    tools = await server.list_tools()

    assert {tool.name for tool in tools} == {
        "crawl_site",
        "list_supported_sites",
        "scrape_page",
        "validate_session",
    }
