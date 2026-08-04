from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP


def create_server() -> FastMCP:
    """Build an MCP server with the public crawling tools."""
    server = FastMCP("python-crawling-mcp")

    @server.tool()
    async def scrape_page(
        url: str, crawl_mode: str = "auto", auth_profile: str | None = None
    ) -> dict[str, Any]:
        """Collect one page."""
        return {"url": url, "crawl_mode": crawl_mode, "auth_profile": auth_profile}

    @server.tool()
    async def crawl_site(
        start_url: str,
        crawl_mode: str = "auto",
        auth_profile: str | None = None,
        max_pages: int = 20,
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Crawl a bounded set of pages starting at a URL."""
        return {
            "start_url": start_url,
            "crawl_mode": crawl_mode,
            "auth_profile": auth_profile,
            "max_pages": max_pages,
            "max_depth": max_depth,
        }

    @server.tool()
    async def validate_session(auth_profile: str) -> dict[str, Any]:
        """Validate a configured authentication session."""
        return {"auth_profile": auth_profile, "valid": False}

    @server.tool()
    async def list_supported_sites() -> dict[str, list[dict[str, str]]]:
        """List registered authentication and extraction adapters."""
        return {"sites": []}

    return server


def main() -> None:
    """Run the MCP server over STDIO."""
    create_server().run(transport="stdio")
