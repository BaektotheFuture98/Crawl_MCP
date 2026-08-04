from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

import uvicorn
from fastapi import Cookie, FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response


@dataclass(slots=True)
class TestSiteState:
    """Development-only session state owned by one FastAPI app."""

    username: str
    password: str
    sessions: set[str] = field(default_factory=set)
    login_count: int = 0


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>{title}</title>
<meta name="description" content="Crawling MCP local development test site"></head>
<body><main>{body}</main></body></html>"""


def create_test_site(*, username: str = "test-user", password: str = "test-password") -> FastAPI:
    """Create the local development login site; never deploy as a production service."""
    app = FastAPI(title="Crawling MCP development test site")
    state = TestSiteState(username=username, password=password)

    def require_session(session: str | None) -> None:
        if session is None or session not in state.sessions:
            raise HTTPException(status_code=401)

    @app.exception_handler(401)
    async def redirect_unauthenticated(_request: object, _error: Exception) -> RedirectResponse:
        return RedirectResponse("/test-site/login", status_code=307)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/test-site/login", response_class=HTMLResponse)
    async def login_page(variant: str = "default") -> str:
        if variant == "missing":
            form = '<form method="post"><p>로그인 UI가 변경되었습니다.</p></form>'
        elif variant == "fallback":
            form = """
            <form method="post"><input name="username" placeholder="사용자 계정">
            <input name="password" type="password" placeholder="암호">
            <button type="submit" data-testid="login-submit">계속</button></form>"""
        else:
            form = """
            <form method="post">
              <label>아이디 <input name="username" autocomplete="username"></label>
              <label>비밀번호 <input name="password" type="password"
                autocomplete="current-password"></label>
              <button type="submit" data-testid="login-submit">로그인</button>
            </form>"""
        return _page("개발용 로그인", f"<h1>개발용 로그인</h1>{form}")

    @app.post("/test-site/login", response_class=HTMLResponse)
    async def login(username: str = Form(), password: str = Form()) -> Response:
        if not secrets.compare_digest(username, state.username) or not secrets.compare_digest(
            password, state.password
        ):
            return HTMLResponse(_page("로그인 실패", "<h1>로그인 실패</h1>"), status_code=401)
        token = secrets.token_urlsafe(24)
        state.sessions.add(token)
        state.login_count += 1
        response = RedirectResponse("/test-site/list", status_code=303)
        response.set_cookie("session", token, httponly=True, samesite="lax")
        return response

    @app.get("/test-site/list", response_class=HTMLResponse)
    async def listing(session: str | None = Cookie(default=None)) -> str:
        require_session(session)
        return _page(
            "목록",
            """<h1>목록</h1><ul>
            <li><a href="/test-site/detail/1">상세 1</a></li>
            <li><a href="/test-site/detail/2">상세 2</a></li></ul>
            <form method="post" action="/test-site/logout">
            <button type="submit">로그아웃</button></form>""",
        )

    @app.get("/test-site/detail/{item_id}", response_class=HTMLResponse)
    async def detail(item_id: int, session: str | None = Cookie(default=None)) -> str:
        require_session(session)
        if item_id not in {1, 2}:
            raise HTTPException(status_code=404)
        return _page(
            f"상세 {item_id}",
            f"""<article data-testid="detail" data-id="{item_id}">
            <h1>상세 항목 {item_id}</h1><p>테스트 상세 본문 {item_id}</p></article>
            <a href="/test-site/list">목록으로</a>
            <form method="post" action="/test-site/logout">
            <button type="submit">로그아웃</button></form>""",
        )

    @app.post("/test-site/logout")
    async def logout(session: str | None = Cookie(default=None)) -> RedirectResponse:
        if session is not None:
            state.sessions.discard(session)
        response = RedirectResponse("/test-site/login", status_code=303)
        response.delete_cookie("session")
        return response

    @app.post("/__test__/expire-sessions")
    async def expire_sessions() -> dict[str, bool]:
        state.sessions.clear()
        return {"expired": True}

    @app.get("/__test__/login-count")
    async def login_count() -> dict[str, int]:
        return {"login_count": state.login_count}

    return app


def main() -> None:
    """Run the development-only test site."""
    app = create_test_site(
        username=os.getenv("TEST_SITE_USERNAME", "test-user"),
        password=os.getenv("TEST_SITE_PASSWORD", "test-password"),
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("TEST_SITE_PORT", "8765")))


if __name__ == "__main__":
    main()
