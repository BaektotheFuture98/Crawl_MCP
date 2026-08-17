# 개발 진행상황

마지막 갱신: 2026-08-17 (Asia/Seoul)

## 저장소와 재개 위치

- 원격 저장소: `https://github.com/BaektotheFuture98/Crawl_MCP.git`
- 현재 로컬 브랜치: `feat/continuous-monitoring`
- 격리 작업 트리: `/Users/seonminbaek/openup/mcp_crawl/python-crawling-mcp/.worktrees/continuous-monitoring`
- 신뢰성 리팩터링 기준 커밋: `b33b378`
- 원격 복구 브랜치: `origin/feature/crawling-mcp`

재개할 때 먼저 실행한다.

```bash
cd /Users/seonminbaek/openup/mcp_crawl/python-crawling-mcp/.worktrees/continuous-monitoring
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
- PostgreSQL 기반 지속 크롤링 target, run, ARTICLE과 target별 관찰 상태
- 전역 canonical ARTICLE을 공유하면서 `(target_id, article_id)` 상태를 분리하는 멱등 저장
- lease heartbeat, owner fencing, 중단된 RUNNING 복구와 실행 직전 단건 claim
- page callback 안에서 추출·저장하고 모니터링 `CrawlResult.items`를 비우는 bounded-memory 처리

## 최근 Conventional Commits

```text
a99e0ef refactor(monitoring): stream article observations
8333b76 fix(monitoring): fence target leases
5653673 fix(storage): isolate article state per target
62fc3ad fix(monitoring): scope article state by target
dcd5ebe docs: plan monitoring reliability refactor
f6f2519 docs: design monitoring reliability refactor
b33b378 refactor(monitoring): persist latest articles in existing ARTICLE
2968034 docs: document continuous crawler operations
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

2026-08-17 `feat/continuous-monitoring` 격리 작업 트리에서 아래 명령을 새로 실행했다.

```text
uv run ruff check .: passed
uv run ruff format --check .: passed (129 files)
uv run mypy src: passed (74 source files)
uv run pytest -q: 154 passed, 29 deselected
uv run alembic upgrade head: passed (20260817_02 head)
CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 uv run pytest -m integration -q: 29 passed, 154 deselected
```

통합 테스트는 전역 ARTICLE 재사용, target별 상태 분리, 동시 upsert, 모니터링 실행 집계,
lease owner fencing과 중단 실행 복구뿐 아니라 공개 수집, 인증, 브라우저, egress 정책도
함께 검증한다.

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

## 통합 상태

두 번째 독립 코드 리뷰에서 기존 4개 Important와 1개 Moderate가 모두 해결됐고,
새 merge blocker가 없다는 판정을 받았다.

- 2026-08-05 사용자가 로컬 `main` 병합을 선택했다.
- `main`은 `14e8f15`에서 `1e3222a`로 fast-forward 병합됐다.
- 병합된 `main`의 전체 로컬·Playwright·Docker 검증이 통과했다.
- 선택한 방식에 따라 `origin/main`은 아직 생성하거나 push하지 않았다.
- 구현 이력은 `origin/feature/crawling-mcp`에 보존되어 있다.

## 참고 문서

- 설계: `docs/superpowers/specs/2026-08-04-python-crawling-mcp-design.md`
- 구현 계획: `docs/superpowers/plans/2026-08-04-python-crawling-mcp-implementation.md`
- 사용·확장·배포: `README.md`
