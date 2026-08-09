from __future__ import annotations

from typing import Any, Self
from uuid import UUID

from crawling_mcp.domain.enums import ErrorCode
from crawling_mcp.domain.models import ErrorResponse


class CrawlError(Exception):
    """Base class for errors safe to classify for MCP clients."""

    code = ErrorCode.NAVIGATION_ERROR
    default_message = "크롤링 작업을 완료하지 못했습니다."

    def __init__(
        self,
        message: str | None = None,
        *,
        job_id: UUID | None = None,
        **details: Any,
    ) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.job_id = job_id
        self.details = details
        self.artifacts: dict[str, str] = {}

    def attach_job_id(self, job_id: UUID) -> Self:
        """Correlate an existing domain error with its crawl job."""
        if self.job_id is None:
            self.job_id = job_id
        return self

    def to_response(self, job_id: UUID | None = None) -> ErrorResponse:
        """Create a traceback-free client response."""
        return ErrorResponse(
            error_code=self.code,
            message=self.message,
            job_id=job_id or self.job_id,
            details=self.details,
        )


class InvalidUrlError(CrawlError):
    code = ErrorCode.INVALID_URL
    default_message = "유효하지 않은 URL입니다."


class BlockedUrlError(CrawlError):
    code = ErrorCode.BLOCKED_URL
    default_message = "보안 정책에 의해 차단된 URL입니다."


class UnsupportedSiteError(CrawlError):
    code = ErrorCode.UNSUPPORTED_SITE
    default_message = "등록되지 않은 인증 사이트입니다."


class AuthenticationRequiredError(CrawlError):
    code = ErrorCode.AUTHENTICATION_REQUIRED
    default_message = "이 페이지에는 등록된 인증 프로필이 필요합니다."


class AuthenticationFailedError(CrawlError):
    code = ErrorCode.AUTHENTICATION_FAILED
    default_message = "등록된 인증 프로필로 로그인하지 못했습니다."


class SessionExpiredError(CrawlError):
    code = ErrorCode.SESSION_EXPIRED
    default_message = "저장된 인증 세션이 만료되었습니다."


class NavigationError(CrawlError):
    code = ErrorCode.NAVIGATION_ERROR
    default_message = "페이지에 접속하지 못했습니다."


class ExtractionError(CrawlError):
    code = ErrorCode.EXTRACTION_ERROR
    default_message = "페이지 데이터를 추출하지 못했습니다."


class CrawlLimitExceededError(CrawlError):
    code = ErrorCode.CRAWL_LIMIT_EXCEEDED
    default_message = "허용된 크롤링 제한을 초과했습니다."
