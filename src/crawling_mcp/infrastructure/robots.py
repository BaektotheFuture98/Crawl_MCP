from __future__ import annotations

import asyncio
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from crawling_mcp.domain.errors import CrawlError, NavigationError
from crawling_mcp.ports.crawler import UrlValidator
from crawling_mcp.ports.network import EgressProxyPort


class RobotsTxtChecker:
    """Fetch and cache robots.txt through the validated egress path."""

    def __init__(
        self,
        *,
        validator: UrlValidator,
        egress_proxy: EgressProxyPort | None = None,
        user_agent: str = "python-crawling-mcp",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._validator = validator
        self._egress_proxy = egress_proxy
        self._user_agent = user_agent
        self._timeout = timeout_seconds
        self._cache: dict[str, RobotFileParser] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _robots_url(url: str) -> tuple[str, str]:
        parts = urlsplit(url)
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        return origin, f"{origin}/robots.txt"

    async def _load(self, origin: str, robots_url: str) -> RobotFileParser:
        parser = RobotFileParser(robots_url)
        try:
            await self._validator.validate(robots_url)
            async with httpx.AsyncClient(
                proxy=self._egress_proxy.url if self._egress_proxy is not None else None,
                follow_redirects=True,
                timeout=self._timeout,
                trust_env=False,
            ) as client:
                response = await client.get(robots_url)
            await self._validator.validate(str(response.url))
        except CrawlError:
            raise
        except (httpx.HTTPError, TimeoutError) as error:
            raise NavigationError(url=robots_url, reason="robots_fetch_failed") from error
        if response.status_code in {401, 403}:
            parser.parse(["User-agent: *", "Disallow: /"])
        elif response.status_code in {408, 429} or response.status_code >= 500:
            raise NavigationError(
                url=robots_url,
                reason="robots_unavailable",
                status_code=response.status_code,
            )
        elif response.status_code >= 400:
            parser.parse(["User-agent: *", "Disallow:"])
        else:
            parser.parse(response.text.splitlines())
        self._cache[origin] = parser
        return parser

    async def allowed(self, url: str) -> bool:
        """Return the cached robots decision for the requested URL."""
        origin, robots_url = self._robots_url(url)
        parser = self._cache.get(origin)
        if parser is None:
            lock = self._locks.setdefault(origin, asyncio.Lock())
            async with lock:
                parser = self._cache.get(origin)
                if parser is None:
                    parser = await self._load(origin, robots_url)
        return parser.can_fetch(self._user_agent, url)
