from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

PlaywrightFactory = Callable[[], Any]


class BrowserManager:
    """Own one Playwright browser and create isolated job contexts."""

    def __init__(
        self,
        *,
        headless: bool = True,
        max_contexts: int = 3,
        playwright_factory: PlaywrightFactory = async_playwright,
    ) -> None:
        self._headless = headless
        self._semaphore = asyncio.Semaphore(max_contexts)
        self._factory = playwright_factory
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start Playwright and Chromium once."""
        async with self._lock:
            if self._browser is not None:
                return
            self._playwright = await self._factory().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)

    @asynccontextmanager
    async def context(self, storage_state: Path | None = None) -> AsyncIterator[BrowserContext]:
        """Yield an isolated context and always close it."""
        await self.start()
        if self._browser is None:
            raise RuntimeError("browser failed to start")
        async with self._semaphore:
            options: dict[str, Any] = {"ignore_https_errors": False}
            state_exists = (
                await asyncio.to_thread(storage_state.is_file)
                if storage_state is not None
                else False
            )
            if storage_state is not None and state_exists:
                options["storage_state"] = str(storage_state)
            browser_context = await self._browser.new_context(**options)
            try:
                yield browser_context
            finally:
                await browser_context.close()

    async def close(self) -> None:
        """Close Browser before Playwright and tolerate repeated calls."""
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
