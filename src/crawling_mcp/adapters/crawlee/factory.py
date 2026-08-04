from __future__ import annotations

from crawling_mcp.domain.enums import CrawlMode
from crawling_mcp.domain.errors import AuthenticationRequiredError
from crawling_mcp.ports.crawler import CrawlerEngine


class CrawlerFactory:
    """Select crawler strategies without storing per-job state."""

    def __init__(
        self, *, http: CrawlerEngine, browser: CrawlerEngine, adaptive: CrawlerEngine
    ) -> None:
        self._http = http
        self._browser = browser
        self._adaptive = adaptive

    def get(self, mode: CrawlMode, *, authenticated: bool = False) -> CrawlerEngine:
        """Return the requested engine, enforcing authenticated browser use."""
        if authenticated:
            if mode is CrawlMode.HTTP:
                raise AuthenticationRequiredError(reason="http_mode_does_not_support_auth")
            return self._browser
        if mode is CrawlMode.HTTP:
            return self._http
        if mode is CrawlMode.BROWSER:
            return self._browser
        return self._adaptive
