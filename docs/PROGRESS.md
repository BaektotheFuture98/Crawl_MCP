# 개발 진행상황

마지막 갱신: 2026-08-04 (Asia/Seoul)

## 저장소와 재개 위치

- 원격 저장소: `https://github.com/BaektotheFuture98/Crawl_MCP.git`
- 작업 브랜치: `feature/crawling-mcp`
- 기준 브랜치: `main`
- 작업 worktree: `/Users/seonminbaek/openup/mcp_crawl/python-crawling-mcp/.worktrees/crawling-mcp`
- 이 문서 직전 구현 체크포인트: `642b7b9`

재개할 때 먼저 실행한다.

```bash
cd /Users/seonminbaek/openup/mcp_crawl/python-crawling-mcp/.worktrees/crawling-mcp
git status --short --branch
git log --oneline -15
git fetch origin
```

## 완료된 구현

- Python 3.12, uv lockfile, MCP SDK 1.29.0, Crawlee 1.9.0, Playwright 1.62.0 프로젝트
- FastMCP STDIO 서버와 lifespan 기반 공유 Playwright/Chromium/egress proxy 관리
- `scrape_page`, `crawl_site`, `validate_session`, `list_supported_sites` Tool
- Domain/Application/Ports/Infrastructure Adapter로 분리한 헥사고날 구조
- HTTP, browser, adaptive 전략과 factory, 사이트별 START/LIST/DETAIL navigation registry
- Crawlee RequestQueue, 브라우저 bounded worker queue, max pages/depth/retries/concurrency/delay
- HTTP와 browser robots.txt 정책, include/exclude, same-domain, URL 정규화·중복 제거
- Generic/Example extractor와 domain registry
- InMemory/File repository, atomic JSON persistence, page 단위 성공·실패 집계
- YAML 인증 profile, 환경변수 secret, Playwright storage state 저장·재사용·만료 후 재로그인
- profile별 refresh lock, 고유 임시 파일, 0600 권한, `{profile}.json` 경로 강제
- resilient login locator와 명시적 로그인 성공 검증
- FastAPI 개발용 로그인/목록/상세/robots/concurrency/retry 테스트 사이트
- best-effort 실패 error/HTML/screenshot/accessibility artifact와 credential redaction
- 구조화된 domain/MCP 오류, transport 단계 type validation 오류 변환, terminal job correlation
- 운영 상한, DNS timeout, 요청 timeout, 전체 작업 deadline
- URL/DNS SSRF 방어와 검증 IP에 직접 연결하는 loopback egress proxy
- redirect 및 Chromium iframe·이미지·스크립트 등 하위 리소스의 동일 egress 정책
- production-safe Docker Compose와 private network를 명시적으로 허용하는 test override
- Dockerfile, `.env.example`, README, 단위·Playwright 통합 테스트

## 최근 Conventional Commits

```text
642b7b9 docs: document crawl resource ceilings
7abcf90 fix(artifacts): preserve concurrent failure diagnostics
aaab84f fix(security): bound crawl resource consumption
319db8d docs: update verified implementation checkpoint
38bcb95 docs: sync runtime limits and security controls
f30772b fix(crawler): retry transient browser failures
eeccfbf fix(storage): avoid blocking repository lookups
71933b5 fix(mcp): structure transport validation errors
eb053e2 fix(security): strengthen URL and log sanitization
1007e9a feat(crawler): add robots-aware concurrent navigation
66f233b fix(core): enforce job limits and page accounting
d815863 fix(auth): serialize session refresh and preserve failures
38af434 fix(security): enforce policy at the egress boundary
51eed00 fix(docker): keep private networking disabled by default
```

## 최신 검증 결과

2026-08-04에 아래 명령을 새로 실행했다.

```text
uv sync --locked: passed (Python 3.12.12, 77 packages audited)
uv run ruff check .: passed
uv run ruff format --check .: passed (83 files)
uv run mypy src: passed (51 source files)
uv run pytest: 99 passed, 20 deselected
uv run pytest -m integration: 20 passed, 99 deselected
docker compose config --quiet: passed
docker compose test override config --quiet: passed
docker compose build: passed
docker compose run --rm -T mcp-server: passed (STDIO start and clean EOF shutdown)
```

통합 테스트는 공개 수집, 로그인, 저장 세션 재사용, 만료 후 재로그인, 목록·상세 탐색,
max pages/depth/concurrency, robots.txt와 5xx fail-closed, include/exclude·중복 제거,
transient 5xx retry, response/link 크기 제한, 실패 artifact, redirect 및 browser subresource
SSRF, egress byte/deadline/handler cleanup을 포함한다.

## 독립 리뷰 조치 내역

초기 독립 리뷰의 병합 차단 항목은 다음과 같이 조치했다.

- DNS 검증과 실제 연결 사이의 rebinding 가능성: 검증 IP pinning egress proxy 도입
- HTTP/Chromium redirect와 subresource 우회: 모든 outbound HTTP(S)를 proxy에 강제
- Docker 기본 사설망 허용: 기본 false, test override/profile에서만 제한적으로 true
- browser robots/concurrency 미적용: robots checker와 bounded worker queue 적용
- auto site crawl 비적응: HTTP start probe 후 browser 선택
- job failure/timeout 미저장: job ID를 먼저 만들고 terminal failure까지 repository에 저장
- 인증 state 경쟁: profile lock, atomic unique temp, mode 0600 적용
- artifact 실패가 원본 오류를 대체: 전체 capture를 best-effort 처리
- item 수와 page 수 혼용: page outcome count를 별도 저장
- transport validation bypass: FastMCP 경계의 구조화 오류 변환 추가
- AUTO probe robots 선행 위반: probe 전 robots 확인, HTTP/browser와 동일 정책 적용
- 응답·링크 크기 무제한: content, link, egress connection byte 상한 적용
- `final_url` query secret 노출: `_url`/`_uri` 계열 로그 필드 전체 URL redaction
- 다수 DNS 답변과 누적 connect timeout: answer 상한과 전체 connect deadline 적용
- proxy 종료 시 활성 handler 잔류: handler 추적·취소 후 listener 종료
- 동시 실패 artifact 덮어쓰기: 최초 표준 경로와 이후 고유 failure 하위 경로 사용

## 남은 절차

기능 구현과 로컬·Docker 검증은 완료 상태다. `main` 통합 전 절차만 남아 있다.

1. 현재 HEAD에 대한 두 번째 독립 코드 리뷰 결과를 확인한다.
2. merge blocker가 있으면 테스트 우선으로 수정하고 위 전체 검증을 다시 실행한다.
3. blocker가 없으면 `feature/crawling-mcp`를 `main`에 통합한다.
4. `origin/main`과 feature branch를 push하고 최종 상태를 이 문서에 기록한다.

## 참고 문서

- 설계: `docs/superpowers/specs/2026-08-04-python-crawling-mcp-design.md`
- 구현 계획: `docs/superpowers/plans/2026-08-04-python-crawling-mcp-implementation.md`
- 사용·확장·배포: `README.md`
