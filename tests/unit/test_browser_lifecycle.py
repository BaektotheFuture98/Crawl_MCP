from __future__ import annotations

from typing import Any

import pytest

from crawling_mcp.infrastructure.browser import BrowserManager


class FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    async def new_context(self, **options: Any) -> Any:
        raise AssertionError("not used")

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.launch_options: dict[str, Any] = {}
        self.browser = FakeBrowser()

    async def launch(self, **options: Any) -> FakeBrowser:
        self.launch_options = options
        if self.fail:
            raise RuntimeError("launch failed")
        return self.browser


class FakePlaywright:
    def __init__(self, *, fail: bool = False) -> None:
        self.chromium = FakeChromium(fail=fail)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class FakeStarter:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> FakePlaywright:
        return self.playwright


class FakeFactory:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.starter = FakeStarter(playwright)

    def __call__(self) -> FakeStarter:
        return self.starter


class FakeProxy:
    url = "http://127.0.0.1:43210"


@pytest.mark.asyncio
async def test_browser_uses_policy_proxy_without_loopback_bypass() -> None:
    playwright = FakePlaywright()
    manager = BrowserManager(
        playwright_factory=FakeFactory(playwright),
        egress_proxy=FakeProxy(),
    )

    await manager.start()
    await manager.close()

    assert playwright.chromium.launch_options["proxy"] == {"server": FakeProxy.url}
    assert "--proxy-bypass-list=<-loopback>" in playwright.chromium.launch_options["args"]
    assert playwright.chromium.browser.closed
    assert playwright.stopped


@pytest.mark.asyncio
async def test_browser_start_rolls_back_playwright_when_launch_fails() -> None:
    playwright = FakePlaywright(fail=True)
    manager = BrowserManager(playwright_factory=FakeFactory(playwright))

    with pytest.raises(RuntimeError, match="launch failed"):
        await manager.start()

    assert playwright.stopped
