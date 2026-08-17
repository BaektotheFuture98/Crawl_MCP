from __future__ import annotations

import asyncio
from contextlib import suppress
from urllib.parse import urlsplit

from crawling_mcp.application.ports.outbound.crawler import UrlValidator
from crawling_mcp.domain.errors import CrawlError, InvalidUrlError
from crawling_mcp.domain.models import ValidatedUrl

_HEADER_LIMIT = 65_536
_CONNECT_TIMEOUT_SECONDS = 15.0
_MAX_UPSTREAM_BYTES = 25_000_000


class SafeEgressProxy:
    """Pin outbound HTTP(S) connections to addresses approved by the URL policy."""

    def __init__(
        self,
        *,
        validator: UrlValidator,
        connect_timeout_seconds: float = _CONNECT_TIMEOUT_SECONDS,
        max_upstream_bytes: int = _MAX_UPSTREAM_BYTES,
    ) -> None:
        if connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be positive")
        if max_upstream_bytes < 1:
            raise ValueError("max_upstream_bytes must be positive")
        self._validator = validator
        self._connect_timeout = connect_timeout_seconds
        self._max_upstream_bytes = max_upstream_bytes
        self._server: asyncio.Server | None = None
        self._url: str | None = None
        self._handlers: set[asyncio.Task[None]] = set()

    @property
    def url(self) -> str:
        """Return the loopback proxy URL after startup."""
        if self._url is None:
            raise RuntimeError("egress proxy is not started")
        return self._url

    async def start(self) -> None:
        """Start one loopback-only proxy server."""
        if self._server is not None:
            return
        server = await asyncio.start_server(self._track_client, "127.0.0.1", 0)
        socket = server.sockets[0]
        port = int(socket.getsockname()[1])
        self._server = server
        self._url = f"http://127.0.0.1:{port}"

    async def close(self) -> None:
        """Stop accepting connections and close the listening socket."""
        if self._server is None:
            return
        server = self._server
        server.close()
        self._url = None
        current = asyncio.current_task()
        active = [task for task in self._handlers if task is not current]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        await server.wait_closed()
        self._server = None

    async def _track_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is None:
            await self._handle_client(reader, writer)
            return
        self._handlers.add(task)
        try:
            await self._handle_client(reader, writer)
        finally:
            self._handlers.discard(task)

    async def _connect(
        self, target: ValidatedUrl
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        last_error: OSError | None = None
        async with asyncio.timeout(self._connect_timeout):
            for address in target.addresses:
                try:
                    return await asyncio.wait_for(
                        asyncio.open_connection(address, target.port),
                        timeout=min(3.0, self._connect_timeout),
                    )
                except OSError as error:
                    last_error = error
        raise OSError("no validated address accepted the connection") from last_error

    @staticmethod
    async def _response(writer: asyncio.StreamWriter, status: int, reason: str) -> None:
        body = f"{status} {reason}\n".encode()
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\n".encode()
            + b"Content-Type: text/plain; charset=utf-8\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + body
        )
        await writer.drain()

    @staticmethod
    def _connect_url(authority: str) -> str:
        try:
            parsed = urlsplit(f"//{authority}")
            hostname = parsed.hostname
            port = parsed.port or 443
        except ValueError as error:
            raise InvalidUrlError(reason="invalid_proxy_authority") from error
        if hostname is None or parsed.username is not None or parsed.password is not None:
            raise InvalidUrlError(reason="invalid_proxy_authority")
        display_host = f"[{hostname}]" if ":" in hostname else hostname
        return f"https://{display_host}:{port}/"

    @staticmethod
    def _origin_request(request_line: str, header_lines: list[str]) -> tuple[str, str]:
        try:
            method, target, version = request_line.split(" ", 2)
        except ValueError as error:
            raise InvalidUrlError(reason="invalid_proxy_request") from error
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise InvalidUrlError(reason="proxy_requires_absolute_http_url")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        forwarded = [f"{method} {path} {version}"]
        forwarded.extend(
            line
            for line in header_lines
            if not line.lower().startswith(("connection:", "proxy-connection:"))
        )
        forwarded.append("Connection: close")
        return target, "\r\n".join(forwarded) + "\r\n\r\n"

    async def _tunnel(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        upstream_reader: asyncio.StreamReader,
        upstream_writer: asyncio.StreamWriter,
    ) -> None:
        async def pump(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
            *,
            max_bytes: int | None = None,
        ) -> None:
            transferred = 0
            while data := await reader.read(65_536):
                if max_bytes is not None and transferred + len(data) > max_bytes:
                    remaining = max_bytes - transferred
                    if remaining > 0:
                        writer.write(data[:remaining])
                        await writer.drain()
                    return
                writer.write(data)
                await writer.drain()
                transferred += len(data)

        tasks = {
            asyncio.create_task(pump(client_reader, upstream_writer)),
            asyncio.create_task(
                pump(
                    upstream_reader,
                    client_writer,
                    max_bytes=self._max_upstream_bytes,
                )
            ),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            with suppress(ConnectionError):
                task.result()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            header_bytes = await reader.readuntil(b"\r\n\r\n")
            if len(header_bytes) > _HEADER_LIMIT:
                await self._response(writer, 431, "Request Header Fields Too Large")
                return
            lines = header_bytes.decode("iso-8859-1").split("\r\n")
            request_line = lines[0]
            if request_line.startswith("CONNECT "):
                authority = request_line.split(" ", 2)[1]
                target = await self._validator.validate(self._connect_url(authority))
                upstream_reader, upstream_writer = await self._connect(target)
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
            else:
                target_url, forwarded = self._origin_request(request_line, lines[1:-2])
                target = await self._validator.validate(target_url)
                upstream_reader, upstream_writer = await self._connect(target)
                upstream_writer.write(forwarded.encode("iso-8859-1"))
                await upstream_writer.drain()
            await self._tunnel(reader, writer, upstream_reader, upstream_writer)
        except CrawlError:
            await self._response(writer, 403, "Forbidden")
        except (OSError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            await self._response(writer, 502, "Bad Gateway")
        finally:
            if upstream_writer is not None:
                upstream_writer.close()
                with suppress(OSError):
                    await upstream_writer.wait_closed()
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
