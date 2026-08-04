from __future__ import annotations

import httpx
import pytest

from crawling_mcp.test_site import create_test_site


@pytest.mark.asyncio
async def test_test_site_protects_pages_and_accepts_development_credentials() -> None:
    app = create_test_site(username="test-user", password="test-password")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        protected = await client.get("/test-site/list", follow_redirects=False)
        login = await client.post(
            "/test-site/login",
            data={"username": "test-user", "password": "test-password"},
            follow_redirects=False,
        )
        listing = await client.get("/test-site/list")

    assert protected.status_code == 307
    assert protected.headers["location"].startswith("/test-site/login")
    assert login.status_code == 303
    assert login.headers["location"] == "/test-site/list"
    assert "session" in login.cookies
    assert listing.status_code == 200
    assert "/test-site/detail/1" in listing.text
    assert "/test-site/detail/2" in listing.text


@pytest.mark.asyncio
async def test_test_site_rejects_invalid_development_credentials() -> None:
    app = create_test_site(username="test-user", password="test-password")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/test-site/login", data={"username": "wrong", "password": "wrong"}
        )

    assert response.status_code == 401
    assert "로그인 실패" in response.text


@pytest.mark.asyncio
async def test_test_site_can_expire_sessions_for_integration_tests() -> None:
    app = create_test_site(username="test-user", password="test-password")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/test-site/login",
            data={"username": "test-user", "password": "test-password"},
        )
        before = await client.get("/__test__/login-count")
        await client.post("/__test__/expire-sessions")
        after = await client.get("/test-site/list", follow_redirects=False)

    assert before.json() == {"login_count": 1}
    assert after.status_code == 307
