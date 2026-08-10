from __future__ import annotations

from typing import Any, Protocol, cast
from uuid import UUID

import structlog
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from crawling_mcp.domain.enums import CrawlMode
from crawling_mcp.domain.errors import (
    CrawlError,
    CrawlLimitExceededError,
    InvalidUrlError,
    NavigationError,
)
from crawling_mcp.domain.models import (
    CrawlRequest,
    CrawlResult,
    PageItem,
    ScrapePageRequest,
    SupportedSite,
)
from crawling_mcp.domain.monitoring import (
    ConfigureTargetRequest,
    CrawlChange,
    CrawlChangeDetail,
    CrawlJobSummary,
    CrawlTarget,
    MonitoringRunResult,
)
from crawling_mcp.infrastructure.logging import mask_sensitive


class McpApplication(Protocol):
    """Application surface exposed through MCP."""

    async def scrape_page(self, request: ScrapePageRequest) -> PageItem: ...

    async def crawl_site(self, request: CrawlRequest) -> CrawlResult: ...

    async def validate_session(self, auth_profile: str) -> bool: ...

    def list_supported_sites(self) -> list[SupportedSite]: ...

    async def list_crawl_targets(
        self, *, enabled: bool | None, limit: int
    ) -> list[CrawlTarget]: ...

    async def configure_crawl_target(self, request: ConfigureTargetRequest) -> CrawlTarget: ...

    async def run_crawl_target(self, target_id: UUID) -> MonitoringRunResult: ...

    async def get_crawl_status(
        self, *, target_id: UUID | None, limit: int
    ) -> list[CrawlJobSummary]: ...

    async def get_recent_changes(
        self, *, target_id: UUID | None, limit: int
    ) -> list[CrawlChange]: ...

    async def get_change_detail(self, change_id: UUID) -> CrawlChangeDetail | None: ...


def _error_payload(error: CrawlError) -> dict[str, Any]:
    payload = error.to_response().model_dump(mode="json")
    return cast(dict[str, Any], mask_sensitive(payload))


def _validation_payload(error: ValidationError) -> dict[str, Any]:
    fields = [".".join(str(part) for part in item["loc"]) for item in error.errors()]
    limit_fields = {
        "exclude_patterns",
        "include_patterns",
        "job_timeout_seconds",
        "max_concurrency",
        "max_depth",
        "max_pages",
        "max_request_retries",
        "request_delay_seconds",
        "request_timeout_seconds",
    }
    if any(field.split(".", 1)[0] in limit_fields for field in fields):
        return _error_payload(CrawlLimitExceededError(reason="invalid_request", fields=fields))
    return _error_payload(InvalidUrlError(reason="invalid_request", fields=fields))


def transport_validation_payload(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Convert SDK argument-validation failures into the public error envelope."""
    try:
        if tool_name == "scrape_page":
            ScrapePageRequest.model_validate(arguments)
        elif tool_name == "crawl_site":
            CrawlRequest.model_validate(arguments)
        else:
            return _error_payload(InvalidUrlError(reason="invalid_request"))
    except ValidationError as error:
        return _validation_payload(error)
    return _error_payload(InvalidUrlError(reason="invalid_request"))


def register_tools(server: FastMCP, application: McpApplication) -> None:
    """Register thin MCP tools that only validate, invoke and serialize."""
    logger = structlog.get_logger(__name__)

    @server.tool()
    async def scrape_page(
        url: str,
        crawl_mode: str = CrawlMode.AUTO.value,
        auth_profile: str | None = None,
    ) -> dict[str, Any]:
        """Collect one public or registered authenticated page."""
        try:
            request = ScrapePageRequest.model_validate(
                {"url": url, "crawl_mode": crawl_mode, "auth_profile": auth_profile}
            )
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
        crawl_mode: str = CrawlMode.AUTO.value,
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
            request = CrawlRequest.model_validate(
                {
                    "start_url": start_url,
                    "crawl_mode": crawl_mode,
                    "auth_profile": auth_profile,
                    "max_pages": max_pages,
                    "max_depth": max_depth,
                    "include_patterns": include_patterns or [],
                    "exclude_patterns": exclude_patterns or [],
                    "same_domain_only": same_domain_only,
                    "max_request_retries": max_request_retries,
                    "request_timeout_seconds": request_timeout_seconds,
                    "job_timeout_seconds": job_timeout_seconds,
                    "max_concurrency": max_concurrency,
                    "respect_robots_txt": respect_robots_txt,
                    "request_delay_seconds": request_delay_seconds,
                    "remove_tracking_parameters": remove_tracking_parameters,
                }
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

    @server.tool()
    async def list_crawl_targets(
        enabled: bool | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List bounded monitoring target configuration without crawl content."""
        try:
            targets = await application.list_crawl_targets(enabled=enabled, limit=limit)
            return {
                "count": len(targets),
                "targets": [target.model_dump(mode="json") for target in targets],
            }
        except Exception as error:
            logger.error("unexpected_list_targets_tool_error", error_type=type(error).__name__)
            return _error_payload(NavigationError(reason="internal_error"))

    @server.tool()
    async def configure_crawl_target(
        target_id: str | None = None,
        url: str | None = None,
        interval_seconds: int | None = None,
        enabled: bool | None = None,
        crawl_mode: str | None = None,
        auth_profile: str | None = None,
        max_pages: int | None = None,
        max_depth: int | None = None,
    ) -> dict[str, Any]:
        """Create or update one persistent target through a single high-level command."""
        try:
            request = ConfigureTargetRequest.model_validate(
                {
                    "target_id": target_id,
                    "url": url,
                    "interval_seconds": interval_seconds,
                    "enabled": enabled,
                    "crawl_mode": crawl_mode,
                    "auth_profile": auth_profile,
                    "max_pages": max_pages,
                    "max_depth": max_depth,
                }
            )
            return (await application.configure_crawl_target(request)).model_dump(mode="json")
        except ValidationError as error:
            return _validation_payload(error)
        except (KeyError, ValueError) as error:
            return _error_payload(InvalidUrlError(reason=type(error).__name__))
        except Exception as error:
            logger.error("unexpected_configure_target_tool_error", error_type=type(error).__name__)
            return _error_payload(NavigationError(reason="internal_error"))

    @server.tool()
    async def run_crawl_target(target_id: str) -> dict[str, Any]:
        """Run one configured target on demand without returning page content."""
        try:
            return (await application.run_crawl_target(UUID(target_id))).model_dump(mode="json")
        except (KeyError, ValueError):
            return _error_payload(InvalidUrlError(reason="invalid_target_id"))
        except CrawlError as error:
            return _error_payload(error)
        except Exception as error:
            logger.error("unexpected_run_target_tool_error", error_type=type(error).__name__)
            return _error_payload(NavigationError(reason="internal_error"))

    @server.tool()
    async def get_crawl_status(
        target_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return compact latest worker status records."""
        try:
            parsed_id = UUID(target_id) if target_id else None
            jobs = await application.get_crawl_status(target_id=parsed_id, limit=limit)
            return {"count": len(jobs), "jobs": [job.model_dump(mode="json") for job in jobs]}
        except ValueError:
            return _error_payload(InvalidUrlError(reason="invalid_target_id"))
        except Exception as error:
            logger.error("unexpected_crawl_status_tool_error", error_type=type(error).__name__)
            return _error_payload(NavigationError(reason="internal_error"))

    @server.tool()
    async def get_recent_changes(
        target_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return bounded NEW/UPDATED summaries without article content."""
        try:
            parsed_id = UUID(target_id) if target_id else None
            changes = await application.get_recent_changes(target_id=parsed_id, limit=limit)
            return {
                "count": len(changes),
                "changes": [change.model_dump(mode="json") for change in changes],
            }
        except ValueError:
            return _error_payload(InvalidUrlError(reason="invalid_target_id"))
        except Exception as error:
            logger.error("unexpected_recent_changes_tool_error", error_type=type(error).__name__)
            return _error_payload(NavigationError(reason="internal_error"))

    @server.tool()
    async def get_change_detail(change_id: str) -> dict[str, Any]:
        """Return article content only for one explicitly selected change."""
        try:
            detail = await application.get_change_detail(UUID(change_id))
            if detail is None:
                return _error_payload(InvalidUrlError(reason="change_not_found"))
            return detail.model_dump(mode="json")
        except ValueError:
            return _error_payload(InvalidUrlError(reason="invalid_change_id"))
        except Exception as error:
            logger.error("unexpected_change_detail_tool_error", error_type=type(error).__name__)
            return _error_payload(NavigationError(reason="internal_error"))
