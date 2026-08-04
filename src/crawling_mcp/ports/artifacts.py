from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from crawling_mcp.domain.errors import CrawlError
from crawling_mcp.domain.models import ArtifactPaths


class FailureArtifactPort(Protocol):
    """Capture safe diagnostics for browser and authentication failures."""

    async def capture(
        self,
        job_id: UUID,
        error: CrawlError,
        *,
        page: Any | None = None,
        sensitive_values: tuple[str, ...] = (),
    ) -> ArtifactPaths: ...
