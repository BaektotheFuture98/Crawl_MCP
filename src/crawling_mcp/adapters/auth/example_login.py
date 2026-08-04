from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from urllib.parse import urlencode

from playwright.async_api import BrowserContext, Locator

from crawling_mcp.domain.errors import AuthenticationFailedError
from crawling_mcp.domain.models import Credentials


class LocatorCandidate(Protocol):
    """Small locator surface needed for resilient candidate selection."""

    async def count(self) -> int: ...

    async def is_visible(self) -> bool: ...

    async def is_enabled(self) -> bool: ...


async def choose_usable_locator[LocatorT: LocatorCandidate](
    candidates: Sequence[LocatorT], *, field: str
) -> LocatorT:
    """Select the first unique, visible and enabled locator candidate."""
    for candidate in candidates:
        if await candidate.count() != 1:
            continue
        if await candidate.is_visible() and await candidate.is_enabled():
            return candidate
    raise AuthenticationFailedError(field=field, reason="locator_not_found")


class ExampleLoginAdapter:
    """Form-login adapter for the local development test site."""

    name = "form_login"

    def __init__(self, base_url: str, *, login_variant: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._login_variant = login_variant

    async def is_authenticated(self, context: BrowserContext) -> bool:
        """Validate the session by observing the protected page after navigation."""
        page = await context.new_page()
        try:
            await page.goto(f"{self._base_url}/test-site/list", wait_until="domcontentloaded")
            logout = page.get_by_role("button", name="로그아웃")
            return "/test-site/login" not in page.url and await logout.count() == 1
        finally:
            await page.close()

    async def authenticate(self, context: BrowserContext, credentials: Credentials) -> None:
        """Log in using resilient candidate locators and verify success."""
        page = await context.new_page()
        try:
            login_url = f"{self._base_url}/test-site/login"
            if self._login_variant is not None:
                login_url = f"{login_url}?{urlencode({'variant': self._login_variant})}"
            await page.goto(login_url, wait_until="domcontentloaded")
            username: Locator = await choose_usable_locator(
                [
                    page.get_by_label("아이디"),
                    page.get_by_label("이메일"),
                    page.get_by_placeholder("아이디"),
                    page.locator('input[name="username"]'),
                    page.locator('input[type="email"]'),
                ],
                field="username",
            )
            password: Locator = await choose_usable_locator(
                [
                    page.get_by_label("비밀번호"),
                    page.get_by_placeholder("비밀번호"),
                    page.locator('input[name="password"]'),
                    page.locator('input[type="password"]'),
                ],
                field="password",
            )
            submit: Locator = await choose_usable_locator(
                [
                    page.get_by_role("button", name="로그인"),
                    page.locator('[data-testid="login-submit"]'),
                    page.locator('button[type="submit"]'),
                ],
                field="submit",
            )
            await username.fill(credentials.username)
            await password.fill(credentials.password)
            await submit.click()
            await page.wait_for_load_state("domcontentloaded")
            if "/test-site/login" in page.url:
                raise AuthenticationFailedError(reason="login_rejected")
            if await page.get_by_role("button", name="로그아웃").count() != 1:
                raise AuthenticationFailedError(reason="success_marker_missing")
        finally:
            await page.close()
