from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
import pytest

from crawling_mcp.adapters.outbound.browser import BrowserManager
from crawling_mcp.adapters.outbound.crawling.browser_engine import BrowserCrawlerEngine
from crawling_mcp.adapters.outbound.crawling.http_engine import HttpCrawlerEngine
from crawling_mcp.adapters.outbound.extraction.pages.generic import GenericExtractor
from crawling_mcp.adapters.outbound.extraction.pages.registry import ExtractorRegistry
from crawling_mcp.adapters.outbound.network.egress_proxy import SafeEgressProxy
from crawling_mcp.domain.errors import BlockedUrlError, NavigationError
from crawling_mcp.domain.models import CrawlContext, ScrapePageRequest, ValidatedUrl


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
                body = b"x" * 1024 if path == b"/large" else b"safe"
                response = (
                    b"HTTP/1.1 200 OK\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + body
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


@asynccontextmanager
async def subresource_server() -> AsyncIterator[tuple[int, list[bytes]]]:
    hits: list[bytes] = []
    port = 0

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            path = request.split(b" ", 2)[1]
            hits.append(path)
            if path == b"/subresource":
                body = (
                    f'<html><body><iframe src="http://blocked.test:{port}/private">'
                    "</iframe></body></html>"
                ).encode()
            else:
                body = b"private"
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    try:
        yield port, hits
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_browser_subresources_cannot_bypass_policy_proxy() -> None:
    validator = SelectiveValidator()
    proxy = SafeEgressProxy(validator=validator)
    browser = BrowserManager(egress_proxy=proxy)
    extractors = ExtractorRegistry(default=GenericExtractor())
    await proxy.start()
    await browser.start()
    try:
        async with subresource_server() as (port, hits):
            engine = BrowserCrawlerEngine(
                validator=validator,
                extractors=extractors,
                browser=browser,
            )
            snapshot = await engine.scrape(
                ScrapePageRequest(
                    url=f"http://allowed.test:{port}/subresource",
                    crawl_mode="browser",
                ),
                CrawlContext(domain="allowed.test"),
            )

        assert snapshot.status_code == 200
        assert b"/subresource" in hits
        assert b"/private" not in hits
        assert any("blocked.test" in url for url in validator.urls)
    finally:
        await browser.close()
        await proxy.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proxy_caps_bytes_received_from_one_upstream_connection() -> None:
    validator = SelectiveValidator()
    proxy = SafeEgressProxy(validator=validator, max_upstream_bytes=100)
    await proxy.start()
    try:
        async with (
            redirect_server() as port,
            httpx.AsyncClient(proxy=proxy.url) as client,
        ):
            with pytest.raises(httpx.RemoteProtocolError):
                await client.get(f"http://allowed.test:{port}/large")
    finally:
        await proxy.close()


class HangingProxy(SafeEgressProxy):
    def __init__(self, validator: SelectiveValidator) -> None:
        super().__init__(validator=validator)
        self.connect_started = asyncio.Event()

    async def _connect(
        self, target: ValidatedUrl
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        self.connect_started.set()
        await asyncio.sleep(60)
        raise AssertionError("unreachable")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proxy_close_cancels_active_client_handlers() -> None:
    proxy = HangingProxy(SelectiveValidator())
    await proxy.start()
    proxy_port = int(urlsplit(proxy.url).port or 0)
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(b"GET http://allowed.test/ HTTP/1.1\r\nHost: allowed.test\r\n\r\n")
    await writer.drain()
    await asyncio.wait_for(proxy.connect_started.wait(), timeout=1)

    await asyncio.wait_for(proxy.close(), timeout=1)

    assert await asyncio.wait_for(reader.read(), timeout=1) == b""
    writer.close()
    await writer.wait_closed()
