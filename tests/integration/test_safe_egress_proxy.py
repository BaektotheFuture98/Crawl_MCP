from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
import pytest

from crawling_mcp.adapters.crawlee.browser_engine import BrowserCrawlerEngine
from crawling_mcp.adapters.crawlee.http_engine import HttpCrawlerEngine
from crawling_mcp.adapters.extractors.generic import GenericExtractor
from crawling_mcp.adapters.extractors.registry import ExtractorRegistry
from crawling_mcp.domain.errors import BlockedUrlError, NavigationError
from crawling_mcp.domain.models import CrawlContext, ScrapePageRequest, ValidatedUrl
from crawling_mcp.infrastructure.browser import BrowserManager
from crawling_mcp.infrastructure.egress_proxy import SafeEgressProxy


class SelectiveValidator:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def validate(self, url: str) -> ValidatedUrl:
        self.urls.append(url)
        parsed = urlsplit(url)
        if parsed.hostname == "blocked.test":
            raise BlockedUrlError(domain="blocked.test", reason="test_block")
        return ValidatedUrl(
            url=url,
            hostname=parsed.hostname or "",
            port=parsed.port or 80,
            addresses=("127.0.0.1",),
        )


@asynccontextmanager
async def redirect_server() -> AsyncIterator[int]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            path = request.split(b" ", 2)[1]
            if path == b"/redirect":
                response = (
                    b"HTTP/1.1 302 Found\r\n"
                    b"Location: http://blocked.test/private\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
            else:
                body = b"safe"
                response = (
                    b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\n" + body
                )
            writer.write(response)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    try:
        yield port
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proxy_pins_validated_address_and_blocks_redirect_target() -> None:
    validator = SelectiveValidator()
    proxy = SafeEgressProxy(validator=validator)
    await proxy.start()
    try:
        async with (
            redirect_server() as port,
            httpx.AsyncClient(proxy=proxy.url, follow_redirects=True) as client,
        ):
            response = await client.get(f"http://allowed.test:{port}/")
            blocked = await client.get(f"http://allowed.test:{port}/redirect")

        assert response.text == "safe"
        assert blocked.status_code == 403
        assert any("blocked.test" in url for url in validator.urls)
    finally:
        await proxy.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_http_and_browser_engines_cannot_bypass_policy_proxy() -> None:
    validator = SelectiveValidator()
    proxy = SafeEgressProxy(validator=validator)
    browser = BrowserManager(egress_proxy=proxy)
    extractors = ExtractorRegistry(default=GenericExtractor())
    await proxy.start()
    await browser.start()
    try:
        async with redirect_server() as port:
            request = ScrapePageRequest(
                url=f"http://allowed.test:{port}/redirect",
                crawl_mode="http",
            )
            http_engine = HttpCrawlerEngine(
                validator=validator,
                extractors=extractors,
                egress_proxy=proxy,
            )
            browser_engine = BrowserCrawlerEngine(
                validator=validator,
                extractors=extractors,
                browser=browser,
            )

            with pytest.raises(NavigationError):
                await http_engine.scrape(request, CrawlContext(domain="allowed.test"))
            with pytest.raises(BlockedUrlError):
                await browser_engine.scrape(
                    request.model_copy(update={"crawl_mode": "browser"}),
                    CrawlContext(domain="allowed.test"),
                )

        assert sum("blocked.test" in url for url in validator.urls) >= 2
    finally:
        await browser.close()
        await proxy.close()
