# 개발 진행상황

마지막 갱신: 2026-08-04 (Asia/Seoul)

## 저장소와 작업 위치

- 원격 저장소: `https://github.com/BaektotheFuture98/Crawl_MCP.git`
- 작업 브랜치: `feature/crawling-mcp`
- 작업 worktree: `/Users/seonminbaek/openup/mcp_crawl/python-crawling-mcp/.worktrees/crawling-mcp`
- 기준 브랜치: `main`
- 현재 체크포인트 HEAD: 이 문서를 추가하는 커밋

## 구현 완료 범위

- Python 3.12+, uv lockfile, MCP SDK, Crawlee, Playwright, Pydantic v2 기반 프로젝트 구성
- FastMCP STDIO 서버와 서버 lifespan 기반 공유 Chromium 관리
- `scrape_page`, `crawl_site`, `validate_session`, `list_supported_sites` Tool
- Domain/Application/Ports/Infrastructure Adapter로 분리한 헥사고날 구조
- HTTP, browser, adaptive crawler 전략과 factory
- Crawlee RequestQueue 및 START/LIST/DETAIL Router label
- URL 정규화, DNS/IP 기반 SSRF 기본 차단, allowlist, 링크 정책
- Generic/Example extractor와 domain registry
- InMemory/File repository와 atomic JSON persistence
- YAML 인증 profile, 환경변수 secret 조회, Playwright storage state 재사용
- resilient login locator와 명시적 로그인 성공 확인
- FastAPI 개발용 로그인 테스트 사이트
- 실패 error/HTML/screenshot/accessibility artifact 저장과 credential redaction
- Dockerfile, Docker Compose, README, 단위·Playwright 통합 테스트

## 최근 분리 커밋

- `fix(security): handle IPv6 literals safely`
- `fix(auth): harden session reuse and failure artifacts`
- `fix(crawler): isolate queues and enforce retry controls`
- `fix(mcp): return safe validation and internal errors`
- `fix(storage): serialize atomic result persistence`
- `feat(observability): add job-scoped crawl logging`

## 마지막 확인 결과

다음 결과는 이 체크포인트를 만들기 직전에 확인했다.

```text
Ruff check: passed
Ruff format --check: passed
mypy src: passed (47 source files)
default pytest: 71 passed, 9 deselected
Playwright integration: 9 passed, 71 deselected
RequestQueue cleanup targeted integration: 1 passed
docker compose config --quiet: passed (독립 리뷰 실행 환경)
```

완료 선언 전에는 아래 전체 명령을 반드시 새로 실행해야 한다.

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run pytest -m integration
docker compose build
docker compose config
```

## 독립 코드 리뷰 결과와 남은 작업

현재 상태는 체크포인트이며 아직 `main` 병합 준비가 끝나지 않았다.

### 병합 차단 보안 작업

1. HTTP redirect와 Playwright redirect/subresource 요청을 실제 네트워크 전송 전에 검증한다.
2. DNS 검증 결과와 실제 연결 사이의 rebinding 가능성을 transport/egress 경계에서 차단한다.
3. 기본 Docker Compose에서 `ALLOW_PRIVATE_NETWORKS=true`를 제거하고 테스트 전용 override/profile로 분리한다.

### 중요 기능·정합성 작업

1. Browser crawl에도 robots 정책을 적용하고 concurrency 옵션의 실제 의미를 명확히 한다.
2. site crawl의 adaptive HTTP→browser 판단을 단일 페이지와 같은 수준으로 보강한다.
3. crawl 실패/timeout을 repository에 terminal 상태로 저장하고 MCP 오류의 `job_id`와 artifact를 연계한다.
4. FastMCP transport 단계 validation도 일관된 구조화 오류로 변환하고 limit 오류 코드를 구분한다.
5. 설정 기반 운영 상한과 DNS/검증/추출을 포함한 전체 deadline을 구현한다.
6. 인증 storage state 동시 갱신을 lock/고유 temp file로 보호하고 `{profile}.json` 규칙을 강제한다.
7. artifact 저장 자체의 실패가 원래 domain error를 덮지 않도록 전체 capture를 best-effort로 만든다.
8. 사이트별 page classifier/link policy port와 Router handler 분리를 구현한다.
9. page 수와 extractor item 수를 분리해 visited/succeeded/max_pages 집계를 바로잡는다.
10. redirect, rebinding, subresource, robots, timeout, include/exclude, lifecycle에 대한 적대적 테스트를 추가한다.

### 소규모 보강

- `set-cookie`, `proxy-authorization`, `access_token`, `api_key` 등 masking key를 확장한다.
- URL parse 전에 C0 control character를 명시적으로 거부한다.
- browser start 실패와 container close 실패 시 lifecycle cleanup을 보장한다.
- 최종 동작에 맞춰 README 보안·동시성 설명을 다시 검증한다.

## 다음 재개 순서

1. `git status --short`와 이 문서를 읽어 체크포인트를 확인한다.
2. transport-boundary SSRF 테스트를 먼저 작성하고 실패를 확인한다.
3. HTTP redirect 검증과 Playwright request interception/egress 방어를 구현한다.
4. Docker production/test Compose 구성을 분리하고 packaging test를 갱신한다.
5. 나머지 중요 리뷰 항목을 하나씩 테스트 우선으로 수정한다.
6. 전체 로컬·Docker 검증 후 `superpowers:requesting-code-review`를 다시 수행한다.
7. 리뷰 차단 항목이 없을 때만 `feature/crawling-mcp`를 `main`에 통합하고 `origin/main`에 push한다.

## 참고 문서

- 설계: `docs/superpowers/specs/2026-08-04-python-crawling-mcp-design.md`
- 구현 계획: `docs/superpowers/plans/2026-08-04-python-crawling-mcp-implementation.md`
- 사용·확장·배포: `README.md`
