from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator

import pytest_asyncio
import uvicorn

from crawling_mcp.test_site import create_test_site


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest_asyncio.fixture
async def test_site_url() -> AsyncIterator[str]:
    port = _free_port()
    config = uvicorn.Config(
        create_test_site(username="test-user", password="test-password"),
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.02)
    if not server.started:
        task.cancel()
        raise RuntimeError("test site failed to start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
