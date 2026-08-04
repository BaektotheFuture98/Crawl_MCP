from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from crawling_mcp.adapters.mcp.tools import register_tools
from crawling_mcp.bootstrap import ApplicationContainer, build_container
from crawling_mcp.infrastructure.config import Settings
from crawling_mcp.infrastructure.logging import configure_logging


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

    server = FastMCP(
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
