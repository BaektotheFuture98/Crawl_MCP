from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import TextContent

from crawling_mcp.adapters.mcp.tools import register_tools, transport_validation_payload
from crawling_mcp.bootstrap import ApplicationContainer, build_container
from crawling_mcp.infrastructure.config import Settings
from crawling_mcp.infrastructure.logging import configure_logging


class CrawlingFastMCP(FastMCP):
    """FastMCP server that keeps transport validation errors structured."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a registered tool and safely map SDK argument validation errors."""
        try:
            return await super().call_tool(name, arguments)
        except ToolError:
            if name not in {
                "scrape_page",
                "crawl_site",
                "validate_session",
                "list_crawl_targets",
                "configure_crawl_target",
                "run_crawl_target",
                "get_crawl_status",
                "get_recent_article_changes",
                "get_article",
            }:
                raise
            payload = transport_validation_payload(name, arguments)
            content = TextContent(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )
            return ([content], payload)


def create_server(
    *,
    settings: Settings | None = None,
    container: ApplicationContainer | None = None,
) -> FastMCP:
    """Build the STDIO MCP server and lifespan-owned application container."""
    configured = settings or Settings()
    application = container or build_container(configured)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[ApplicationContainer]:
        await application.start()
        try:
            yield application
        finally:
            await application.close()

    server = CrawlingFastMCP(
        "python-crawling-mcp",
        instructions="Secure bounded crawling for public and registered authenticated sites.",
        lifespan=lifespan,
        log_level=configured.log_level,
    )
    register_tools(server, application)
    return server


def main() -> None:
    """Run the MCP server over STDIO."""
    settings = Settings()
    configure_logging(settings.log_level)
    create_server(settings=settings).run(transport="stdio")
