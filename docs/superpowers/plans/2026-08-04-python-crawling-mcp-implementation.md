# Python Crawling MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 안전한 공개·인증 페이지 수집, 제한된 링크 탐색, 세션 재사용, 구조화 오류와 실패 아티팩트를 제공하는 실행 가능한 Python MCP 서버를 완성한다.

**Architecture:** FastMCP Adapter는 Pydantic 입력 검증과 Application Service 호출만 수행한다. `CrawlService`와 `AuthService`는 Domain Protocol에 의존하고, Crawlee/Playwright, 사이트별 인증·추출, 메모리·파일 저장소는 Infrastructure Adapter로 주입한다.

**Tech Stack:** Python 3.12+, uv, MCP Python SDK 1.28.x, Crawlee 1.8.x, Playwright 1.61.x, Pydantic v2, pydantic-settings, structlog, FastAPI, pytest, Ruff, mypy, Docker Compose.

## Global Constraints

- Python 버전은 `>=3.12,<3.15`이다.
- MCP SDK는 `mcp>=1.28.1,<2`, Crawlee는 `crawlee[beautifulsoup,playwright]>=1.8.3,<2`, Playwright는 `playwright>=1.61.0,<2`이다.
- 모든 public 함수와 메서드에 타입 힌트를 작성하고 Pydantic mutable 필드는 `default_factory`를 사용한다.
- MCP Adapter에 Playwright, Crawlee, 파일 저장 구현을 작성하지 않는다.
- URL은 최초 요청, DNS resolution, navigation 직전, redirect 및 발견 링크마다 SSRF 정책을 통과해야 한다.
- password, cookie, Authorization, storage state는 MCP 응답과 로그에 노출하지 않는다.
- 각 Browser 작업은 별도 context를 사용하고 page/context는 `finally`에서 닫는다. Browser 프로세스는 lifespan 동안 재사용한다.
- 단계 종료마다 `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest`를 실행한다.

---

## File Map

- `pyproject.toml`: 런타임·개발 의존성, entry point, Ruff/mypy/pytest 설정
- `src/crawling_mcp/domain/*`: enum, Pydantic 모델, 오류, 순수 URL·탐색 정책
- `src/crawling_mcp/ports/*`: crawler/auth/extractor/repository/browser Protocol
- `src/crawling_mcp/application/*`: 인증과 crawl orchestration
- `src/crawling_mcp/adapters/mcp/tools.py`: 네 MCP Tool 등록과 안전한 오류 변환
- `src/crawling_mcp/adapters/crawlee/*`: HTTP/browser/adaptive engine, factory, Router label
- `src/crawling_mcp/adapters/auth/*`: Registry, no-auth, saved session, example login
- `src/crawling_mcp/adapters/extractors/*`: Registry, generic/example extractor
- `src/crawling_mcp/adapters/storage/*`: memory/file Repository
- `src/crawling_mcp/infrastructure/*`: settings, logging redaction, SSRF resolver, browser manager, failure artifacts
- `src/crawling_mcp/bootstrap.py`: dependency graph 구성
- `src/crawling_mcp/server.py`: FastMCP lifespan과 Tool wiring
- `src/crawling_mcp/test_site.py`: 로컬 개발 로그인 사이트
- `tests/unit/*`: 외부 네트워크 없는 정책·서비스·Adapter 테스트
- `tests/integration/*`: HTTP/Playwright end-to-end 테스트

### Task 1: Project skeleton and executable MCP shell

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `.env.example`, `config/auth_profiles.example.yaml`
- Create: `src/crawling_mcp/__init__.py`, `src/crawling_mcp/__main__.py`, `src/crawling_mcp/server.py`, `src/crawling_mcp/bootstrap.py`
- Create: package `__init__.py` files under `domain`, `application`, `ports`, `adapters`, `infrastructure`
- Test: `tests/unit/test_server.py`

**Interfaces:**
- Produces: `create_server() -> FastMCP`, `main() -> None`, `ApplicationContainer.start()`, `ApplicationContainer.close()`

- [ ] Write a failing test that calls `create_server()` and asserts the registered Tool names are exactly `scrape_page`, `crawl_site`, `validate_session`, `list_supported_sites`.
- [ ] Run `uv run pytest tests/unit/test_server.py -q` and confirm failure because the package/server does not exist.
- [ ] Add the package metadata, conservative settings, STDIO entry point, empty typed container, and thin Tool registrations whose service dependency is injected.
- [ ] Run the server test and `uv run python -m crawling_mcp --help`; confirm import and process startup path work without stdout logging.
- [ ] Run Ruff, format, mypy, and unit tests; commit `feat: scaffold MCP server`.

### Task 2: Domain models, URL normalization, and SSRF security

**Files:**
- Create: `src/crawling_mcp/domain/enums.py`, `models.py`, `errors.py`, `policies.py`
- Create: `src/crawling_mcp/infrastructure/config.py`, `security.py`, `logging.py`
- Create: `tests/unit/test_models.py`, `test_url_policy.py`, `test_security.py`, `test_logging.py`

**Interfaces:**
- Produces: `normalize_url(url: str, remove_tracking: bool = True) -> str`
- Produces: `UrlSecurityValidator.validate(url: str) -> Awaitable[ValidatedUrl]`
- Produces: `CrawlRequest`, `ScrapePageRequest`, `PageItem`, `CrawlResult`, `CrawlFailure`, `ErrorResponse`
- Produces: `CrawlError.to_response(job_id: UUID | None) -> ErrorResponse`

- [ ] Write table-driven failing tests for fragment removal, default port removal, IDNA, stable query ordering, optional tracking removal, include/exclude patterns, same-domain and depth rules.
- [ ] Run the policy tests and confirm missing-symbol failures.
- [ ] Implement pure normalization and pattern/depth policies with bounded Pydantic request fields.
- [ ] Write failing async tests using an injected resolver for public IP acceptance and loopback/private/link-local/metadata/mixed DNS answer rejection, forbidden schemes, credentials, malformed hosts, and allowlist behavior.
- [ ] Implement `UrlSecurityValidator` so every resolved address must be globally routable unless test-only private access is explicitly enabled.
- [ ] Write failing tests for recursive masking of password/cookie/authorization keys and sensitive query values; implement structlog processors that log to stderr.
- [ ] Run all Task 2 tests and quality gates; commit `feat: add crawl domain and URL security`.

### Task 3: Ports, extractors, repositories, and single-page service

**Files:**
- Create: `src/crawling_mcp/ports/crawler.py`, `authentication.py`, `extractor.py`, `repository.py`, `browser.py`
- Create: `src/crawling_mcp/adapters/extractors/registry.py`, `generic.py`, `example.py`
- Create: `src/crawling_mcp/adapters/storage/memory_repository.py`, `file_repository.py`
- Create: `src/crawling_mcp/application/crawl_service.py`
- Test: `tests/unit/test_extractor_registry.py`, `test_generic_extractor.py`, `test_memory_repository.py`, `test_file_repository.py`, `test_crawl_service.py`

**Interfaces:**
- Produces: `CrawlerEngine.scrape(request: ScrapePageRequest, context: CrawlContext) -> Awaitable[PageSnapshot]`
- Produces: `CrawlerEngine.crawl(request: CrawlRequest, context: CrawlContext) -> Awaitable[CrawlResult]`
- Produces: `PageExtractor.extract(snapshot: PageSnapshot) -> Awaitable[list[PageItem]]`
- Produces: `CrawlRepository.start_job`, `save_page`, `save_failure`, `complete_job`, `get_job`
- Produces: `CrawlService.scrape_page`, `CrawlService.crawl_site`

- [ ] Write failing Registry tests for exact domain, explicit subdomain mapping, generic public fallback, and authenticated unsupported-domain rejection.
- [ ] Implement immutable metadata snapshots and extractor lookup.
- [ ] Write a failing GenericExtractor test using real HTML containing removable tags, canonical, description and language; implement engine-neutral HTML extraction.
- [ ] Write failing repository contract tests and run them against InMemory and temporary File repositories, including concurrent updates and atomic JSON persistence.
- [ ] Implement both repositories with `asyncio.Lock` and `asyncio.to_thread` for file I/O.
- [ ] Write failing CrawlService tests proving validation occurs before engine invocation, repository writes occur for success/failure, and traceback/secrets are absent from domain responses.
- [ ] Implement the minimal orchestration against Protocols and run Task 3 tests plus all quality gates; commit `feat: add extraction repositories and crawl service`.

### Task 4: Crawlee strategies, factory, Router, and bounded traversal

**Files:**
- Create: `src/crawling_mcp/adapters/crawlee/http_engine.py`, `browser_engine.py`, `adaptive_engine.py`, `factory.py`, `router.py`
- Test: `tests/unit/test_crawler_factory.py`, `test_router.py`, `test_adaptive_engine.py`, `test_link_policy.py`
- Integration: `tests/integration/test_public_crawl.py`, `test_traversal_limits.py`

**Interfaces:**
- Produces: `CrawlerFactory.get(mode: CrawlMode, authenticated: bool = False) -> CrawlerEngine`
- Produces: `PageRouter.classify(snapshot: PageSnapshot) -> PageType`
- Consumes: Task 2 security/policies and Task 3 extractor/repository/service contracts

- [ ] Write failing Factory tests for `http`, `browser`, `auto`, and explicit HTTP-with-auth rejection; implement stable instance mapping.
- [ ] Write failing Router tests for `START`, `LIST`, `DETAIL` label dispatch and Adapter classifier override; implement Crawlee Router registration without Application-layer imports.
- [ ] Write failing traversal tests for normalized dedupe, fragment/tracker removal, include/exclude, same-domain, max pages, max depth, retry and request/job timeout.
- [ ] Implement HTTP and browser engines using Crawlee request queues and enqueue policy before reservation; guard the page budget with an async lock.
- [ ] Write failing Adaptive tests for HTTP success, empty/JS-shell fallback, auth redirect fallback and no duplicate persistence; implement one browser fallback.
- [ ] Run public local-server integration tests and all quality gates; commit `feat: add bounded Crawlee engines`.

### Task 5: Authentication profiles, adapters, and browser lifecycle

**Files:**
- Create: `src/crawling_mcp/application/auth_service.py`
- Create: `src/crawling_mcp/adapters/auth/registry.py`, `no_auth.py`, `saved_session.py`, `example_login.py`
- Create: `src/crawling_mcp/infrastructure/browser.py`
- Create: `tests/unit/test_auth_profiles.py`, `test_auth_registry.py`, `test_session_paths.py`, `test_auth_service.py`, `test_browser_manager.py`

**Interfaces:**
- Produces: `AuthenticationAdapter.is_authenticated(context: BrowserContextHandle) -> Awaitable[bool]`
- Produces: `AuthenticationAdapter.authenticate(context: BrowserContextHandle, credentials: Credentials) -> Awaitable[None]`
- Produces: `AuthService.context_for(domain: str, profile: str | None) -> AsyncContextManager[BrowserContextHandle]`
- Produces: `BrowserManager.start`, `new_context`, `close`

- [ ] Write failing profile tests for YAML lookup, domain mismatch, missing environment secret, and profile names/path traversal/symlink escape.
- [ ] Implement settings/profile parsing and root-confined storage paths.
- [ ] Write failing AuthService tests for no-auth, valid storage state reuse, expired state login, post-login validation, atomic state refresh and invalid credentials.
- [ ] Implement Registry, NoAuth, SavedSession and state transitions without logging credentials.
- [ ] Write failing locator-selection tests for exactly one visible/enabled candidate and ambiguous/missing candidates.
- [ ] Implement ExampleLoginAdapter candidate priority and explicit post-click success validation.
- [ ] Write lifecycle tests proving one Browser process, separate contexts, context cleanup on exceptions and close ordering; implement BrowserManager.
- [ ] Run Task 5 tests and all quality gates; commit `feat: add authentication and session reuse`.

### Task 6: Local test site and authenticated integration flows

**Files:**
- Create: `src/crawling_mcp/test_site.py`, `config/auth_profiles.yaml`
- Create: `tests/integration/conftest.py`, `test_auth_crawl.py`, `test_session_reuse.py`, `test_session_expiry.py`, `test_login_failures.py`

**Interfaces:**
- Produces routes: `/test-site/login`, `/test-site/list`, `/test-site/detail/1`, `/test-site/detail/2`
- Produces test-only controls for session expiry, login count, locator variant
- Consumes: Task 5 AuthService and Example adapters

- [ ] Write failing FastAPI tests for login cookie issuance, protected redirects, list/detail links and invalid credentials.
- [ ] Implement the development-only app with `test-user`/`test-password` defaults isolated from production profiles.
- [ ] Write failing Playwright integrations for first login, storage-state reuse without a second login, server-side expiry and relogin, detail traversal, invalid password and missing locator.
- [ ] Implement bootstrap registration for the local example domain and test-only private-network override fixture.
- [ ] Run `uv run pytest -m integration` and all quality gates; commit `test: add authenticated crawl test site`.

### Task 7: Failure artifacts, MCP error contracts, and lifespan wiring

**Files:**
- Create: `src/crawling_mcp/infrastructure/artifacts.py`
- Modify: `src/crawling_mcp/adapters/mcp/tools.py`, `bootstrap.py`, `server.py`, crawler/auth adapters
- Test: `tests/unit/test_error_mapping.py`, `test_artifacts.py`, `test_lifespan.py`
- Integration: `tests/integration/test_failure_artifacts.py`, `test_mcp_tools.py`

**Interfaces:**
- Produces: `FailureArtifactWriter.capture(job_id, error, page=None) -> Awaitable[ArtifactPaths]`
- Produces MCP-safe payloads for all nine domain error classes
- Consumes all prior registries, factory, repository and browser lifecycle components

- [ ] Write failing error mapping tests for exact codes and safe details without traceback, password, cookie or authorization values.
- [ ] Implement Tool wrappers that validate input, call services, and convert domain results/errors only.
- [ ] Write failing artifact tests for error JSON, HTML, PNG and accessibility text, plus capture failure that preserves the original error.
- [ ] Implement async artifact capture, recursive redaction and atomic error JSON writes.
- [ ] Write failing lifespan tests proving dependency initialization order, one browser start, shutdown cleanup and Repository closure.
- [ ] Complete bootstrap/server wiring and validate all four MCP Tools through an in-process MCP client.
- [ ] Run failure integrations and all quality gates; commit `feat: add MCP lifecycle and failure artifacts`.

### Task 8: Docker, documentation, and reproducible lockfile

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `README.md`, `uv.lock`
- Modify: `.env.example`, `.gitignore`, profile example
- Test: `tests/unit/test_packaging.py`

**Interfaces:**
- Produces commands: `uv sync`, `uv run playwright install chromium`, `uv run python -m crawling_mcp`
- Produces compose services: `mcp-server`, `test-site`; volumes: auth, results, failures, screenshots

- [ ] Write packaging tests that parse TOML/YAML/Compose and validate non-root user, matching Playwright version, STDIO, services, volumes and ignored secret/data paths.
- [ ] Add Dockerfile with pinned Playwright-compatible base, uv locked install, non-root runtime and writable `/app/data` directories.
- [ ] Add Compose services, env file, healthcheck and named/bind volumes for all required data paths.
- [ ] Write README covering all 15 requested sections, exact MCP client configuration, Tool calls, Adapter/Extractor/profile extension and current limits.
- [ ] Generate `uv.lock`, run `uv sync --locked`, install Chromium and run all quality gates.
- [ ] Run Docker build, Compose config, test-site healthcheck and an MCP server startup smoke test; commit `docs: add deployment and operations guide`.

### Task 9: Completion audit and branch handoff

**Files:**
- Review: design specification, implementation plan, source, tests, README and deployment files

**Interfaces:**
- Verifies every original numbered requirement and final deliverable against a source path or command output.

- [ ] Run `git diff --check` and confirm no unrelated/uncommitted generated artifacts.
- [ ] Run fresh full gates: Ruff check, Ruff format check, mypy, unit/default pytest, integration pytest.
- [ ] Run fresh local smoke tests for `python -m crawling_mcp`, public scrape, authenticated crawl, session validation and supported-site listing.
- [ ] Run Docker build and Compose config/start/health/stop checks without deleting persistent user data.
- [ ] Record pass counts, skipped tests, environment limitations and any unmet requirement; do not declare completion if evidence is missing.
- [ ] Invoke `superpowers:finishing-a-development-branch` and offer merge/push/PR handoff choices.
