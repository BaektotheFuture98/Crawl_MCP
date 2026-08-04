from __future__ import annotations

from enum import StrEnum


class CrawlMode(StrEnum):
    """Available crawler strategies."""

    AUTO = "auto"
    HTTP = "http"
    BROWSER = "browser"


class PageType(StrEnum):
    """Router labels used during traversal."""

    START = "START"
    LIST = "LIST"
    DETAIL = "DETAIL"


class ErrorCode(StrEnum):
    """Stable error codes returned to MCP clients."""

    INVALID_URL = "INVALID_URL"
    BLOCKED_URL = "BLOCKED_URL"
    UNSUPPORTED_SITE = "UNSUPPORTED_SITE"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    NAVIGATION_ERROR = "NAVIGATION_ERROR"
    EXTRACTION_ERROR = "EXTRACTION_ERROR"
    CRAWL_LIMIT_EXCEEDED = "CRAWL_LIMIT_EXCEEDED"
