from __future__ import annotations

from typing import Any, Protocol, cast

import structlog
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from crawling_mcp.domain.enums import CrawlMode
from crawling_mcp.domain.errors import CrawlError, InvalidUrlError, NavigationError
from crawling_mcp.domain.models import (
    CrawlRequest,
    CrawlResult,
    PageItem,
    ScrapePageRequest,
    SupportedSite,
)
from crawling_mcp.infrastructure.logging import mask_sensitive


class McpApplication(Protocol):
    """Application surface exposed through MCP."""

    async def scrape_page(self, request: ScrapePageRequest) -> PageItem: ...

    async def crawl_site(self, request: CrawlRequest) -> CrawlResult: ...

    async def validate_session(self, auth_profile: str) -> bool: ...

    def list_supported_sites(self) -> list[SupportedSite]: ...


def _error_payload(error: CrawlError) -> dict[str, Any]:
    payload = error.to_response().model_dump(mode="json")
    return cast(dict[str, Any], mask_sensitive(payload))


def _validation_payload(error: ValidationError) -> dict[str, Any]:
    fields = [".".join(str(part) for part in item["loc"]) for item in error.errors()]
    return _error_payload(InvalidUrlError(reason="invalid_request", fields=fields))


def register_tools(server: FastMCP, application: McpApplication) -> None:
    """Register thin MCP tools that only validate, invoke and serialize."""
    logger = structlog.get_logger(__name__)

    @server.tool()
    async def scrape_page(
        url: str, crawl_mode: CrawlMode = CrawlMode.AUTO, auth_profile: str | None = None
    ) -> dict[str, Any]:
        """Collect one public or registered authenticated page."""
        try:
            request = ScrapePageRequest(url=url, crawl_mode=crawl_mode, auth_profile=auth_profile)
            return (await application.scrape_page(request)).model_dump(mode="json")
        except CrawlError as error:
            return _error_payload(error)
        except ValidationError as error:
            return _validation_payload(error)
        except Exception as error:
            logger.error("unexpected_scrape_tool_error", error_type=type(error).__name__)
            return _error_payload(NavigationError(reason="internal_error"))

    @server.tool()
    async def crawl_site(
        start_url: str,
        crawl_mode: CrawlMode = CrawlMode.AUTO,
        auth_profile: str | None = None,
        max_pages: int = 20,
        max_depth: int = 2,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        same_domain_only: bool = True,
        max_request_retries: int = 2,
        request_timeout_seconds: int = 30,
        job_timeout_seconds: int = 300,
        max_concurrency: int = 3,
        respect_robots_txt: bool = True,
        request_delay_seconds: float = 0.5,
        remove_tracking_parameters: bool = True,
    ) -> dict[str, Any]:
        """Explore a bounded set of links from a start URL."""
        try:
            request = CrawlRequest(
                start_url=start_url,
                crawl_mode=crawl_mode,
                auth_profile=auth_profile,
                max_pages=max_pages,
                max_depth=max_depth,
                include_patterns=include_patterns or [],
                exclude_patterns=exclude_patterns or [],
                same_domain_only=same_domain_only,
                max_request_retries=max_request_retries,
                request_timeout_seconds=request_timeout_seconds,
                job_timeout_seconds=job_timeout_seconds,
                max_concurrency=max_concurrency,
                respect_robots_txt=respect_robots_txt,
                request_delay_seconds=request_delay_seconds,
                remove_tracking_parameters=remove_tracking_parameters,
            )
            return (await application.crawl_site(request)).model_dump(mode="json")
        except CrawlError as error:
            return _error_payload(error)
        except ValidationError as error:
            return _validation_payload(error)
        except Exception as error:
            logger.error("unexpected_crawl_tool_error", error_type=type(error).__name__)
            return _error_payload(NavigationError(reason="internal_error"))

    @server.tool()
    async def validate_session(auth_profile: str) -> dict[str, Any]:
        """Check whether a saved authentication profile session is valid."""
        try:
            valid = await application.validate_session(auth_profile)
            return {"auth_profile": auth_profile, "valid": valid}
        except CrawlError as error:
            return _error_payload(error)
        except Exception as error:
            logger.error("unexpected_session_tool_error", error_type=type(error).__name__)
            return _error_payload(NavigationError(reason="internal_error"))

    @server.tool()
    async def list_supported_sites() -> dict[str, Any]:
        """List registered site adapters without exposing profile secrets."""
        return {
            "sites": [site.model_dump(mode="json") for site in application.list_supported_sites()]
        }
