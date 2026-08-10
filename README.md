# Python Crawling MCP

Python Crawling MCP는 MCP Client가 요청한 공개 페이지와 사전에 등록된 인증 사이트를 안전하게 수집하는 STDIO 서버입니다. 임의 사이트의 로그인 방법을 추측하지 않으며, 지원 사이트마다 로그인·세션 검증·페이지 분류·추출 규칙을 Adapter로 등록합니다.

잠금 파일 기준 주요 버전은 Python 3.12, MCP Python SDK 1.29.0, Crawlee 1.9.0, Playwright 1.62.0, Pydantic 2.13.4입니다.

## 아키텍처

```text
FastMCP Adapter
    ↓ 입력 검증, Application Service 호출, 응답 직렬화
CrawlService ── AuthService ── MonitoringService
    ↓ Protocol ports
CrawlerEngine / AuthenticationAdapter / PageExtractor / CrawlRepository / Monitoring ports
    ↑
Crawlee HTTP / shared Playwright browser / validated egress proxy / registries / storage
```

MCP Tool은 Playwright와 Crawlee를 직접 사용하지 않습니다. `CrawlService`는 Protocol에만 의존하므로 같은 로직을 CLI, REST API 또는 Worker Adapter에서 재사용할 수 있습니다. 서버 lifespan이 Playwright와 Chromium을 한 번 시작하고, 작업별 BrowserContext로 세션을 격리합니다.

지속 크롤링은 Hermes가 MCP를 polling하는 대신 별도 Python Worker가 담당합니다.

```text
Hermes -> MCP query/command tools -> MonitoringQueryService -> PostgreSQL

Crawler Worker -> MonitoringService -> CrawlService -> Adaptive Engine
                                      -> HTTP / shared Playwright
                                      -> ChangeDetector -> PostgreSQL
```

반복 가능한 수집·비교·저장은 Python 코드에서 수행하고, Hermes는 변경이 발생한 뒤 분석·요약·판단이 필요할 때만 호출합니다.

## 디렉터리

```text
src/crawling_mcp/
├── domain/           # 모델, enum, 오류, URL·링크 정책
├── application/      # CrawlService, AuthService
├── ports/            # crawler/auth/extractor/repository/browser/network/robots Protocol
├── adapters/
│   ├── mcp/          # 네 MCP Tool
│   ├── worker/       # polling scheduler와 graceful runner
│   ├── crawlee/      # HTTP/browser/adaptive engine, factory, router
│   ├── auth/         # registry, no-auth, saved session, example login
│   ├── extractors/   # generic/example extractor와 registry
│   └── storage/      # memory/file 및 PostgreSQL repository
├── infrastructure/   # 설정, SSRF, egress proxy, robots, logging, browser, artifacts
├── bootstrap.py      # dependency composition root
├── server.py         # FastMCP lifespan
└── test_site.py      # 개발 전용 로그인 사이트
```

운영 crawl target, snapshot, change와 article은 PostgreSQL에 저장합니다. FileRepository는 기존 단일 프로세스 수동 크롤링 호환성을 위해 유지됩니다.

## 로컬 설치와 실행

Python 3.12 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
uv run alembic upgrade head
uv run python -m crawling_mcp
```

Worker는 별도 프로세스로 실행합니다.

```bash
uv run python -m crawling_mcp.worker
```

Worker는 MCP를 호출하지 않고 `MonitoringService -> CrawlService`를 직접 호출합니다. 지속 크롤링 Worker는 `CRAWLING_MCP_REPOSITORY=postgres`에서만 시작됩니다.

서버는 STDIO transport를 사용합니다. stdout은 MCP protocol 전용이고 구조화 로그는 stderr로 출력됩니다.

개발용 로그인 사이트는 별도 터미널에서 실행합니다.

```bash
uv run python -m crawling_mcp.test_site
```

개발 계정은 `test-user` / `test-password`입니다. 이 값은 로컬 테스트 전용이며 운영 계정으로 사용하면 안 됩니다.

## Docker 실행

`.env`를 만든 후 다음을 실행합니다.

```bash
cp .env.example .env
docker compose up -d
```

기본 Compose는 PostgreSQL 18, Alembic migration, MCP Server, Crawler Worker를 순서대로 시작합니다. MinIO는 사용하지 않습니다.

기본 Compose는 사설망 접근을 차단하며 테스트 사이트를 시작하지 않습니다. 로컬 Docker 인증 예제는 명시적인 test override와 profile로 실행합니다.

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml --profile test up -d test-site
docker compose -f docker-compose.yml -f docker-compose.test.yml --profile test run --rm -T mcp-server
```

test override는 private-network 허용과 domain allowlist를 `test-site` 하나로 함께 제한합니다. 인터넷 대상 운영 배포에서는 기본 `CRAWLING_MCP_ALLOW_PRIVATE_NETWORKS=false`를 유지하십시오. 인증, 결과, 실패, 스크린샷 디렉터리는 각각 별도 named volume입니다. 이미지는 비-root `crawling` 사용자로 실행됩니다.

## MCP Client 연결

Codex, Claude Desktop 등 STDIO MCP Client에서는 절대 경로를 사용합니다.

```json
{
  "mcpServers": {
    "python-crawling-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/python-crawling-mcp",
        "run",
        "python",
        "-m",
        "crawling_mcp"
      ]
    }
  }
}
```

## MCP Tools

MCP에는 기존 수동 크롤링 Tool과 지속 크롤링용 고수준 Tool이 함께 등록됩니다.

### `scrape_page`

```json
{
  "url": "https://example.com/page",
  "crawl_mode": "auto",
  "auth_profile": null
}
```

성공 결과에는 `url`, `title`, `content`, `metadata`, `meta_description`, `canonical_url`, `language`, `http_status_code`, `collected_at`이 포함됩니다.

### `crawl_site`

```json
{
  "start_url": "https://example.com",
  "crawl_mode": "auto",
  "auth_profile": null,
  "max_pages": 20,
  "max_depth": 2,
  "include_patterns": [],
  "exclude_patterns": [],
  "same_domain_only": true,
  "max_request_retries": 2,
  "request_timeout_seconds": 30,
  "job_timeout_seconds": 300,
  "max_concurrency": 3,
  "respect_robots_txt": true,
  "request_delay_seconds": 0.5,
  "remove_tracking_parameters": true
}
```

결과에는 job ID, 방문/성공/실패 수, items, failures, 시작/완료 시각이 포함됩니다. URL fragment와 선택한 tracking parameter를 제거한 URL이 중복 키로 사용됩니다.

### `validate_session`

```json
{"auth_profile": "example-reader"}
```

저장된 Playwright storage state를 격리된 context에 로드한 뒤 사이트 Adapter의 실제 인증 표식을 확인합니다. 만료 세션을 자동 갱신하지는 않으며 `scrape_page` 또는 `crawl_site` 호출 때 재로그인합니다.

### `list_supported_sites`

등록된 domain, authentication Adapter 이름, extractor 이름만 반환합니다. 환경변수 이름, storage path와 secret은 반환하지 않습니다.

### `configure_crawl_target`

target ID 없이 호출하면 생성하고, ID가 있으면 전달한 필드만 수정합니다.

```json
{
  "url": "https://example.com/news",
  "interval_seconds": 300,
  "enabled": true,
  "crawl_mode": "auto",
  "max_pages": 20,
  "max_depth": 2
}
```

### `list_crawl_targets`

```json
{"enabled": true, "limit": 50}
```

설정과 스케줄 상태만 반환하며 기사 본문은 반환하지 않습니다.

### `run_crawl_target`

```json
{"target_id": "0198..."}
```

등록 target을 즉시 한 번 실행하고 checked/changed/new/updated/unchanged/failed 집계만 반환합니다.

### `get_crawl_status`

```json
{"target_id": "0198...", "limit": 20}
```

최근 Worker job 집계를 반환합니다. target ID를 생략하면 여러 target의 최신 상태를 반환합니다.

### `get_recent_changes`

```json
{"target_id": "0198...", "limit": 20}
```

`change_id`, URL, change type, 제목, 감지시간만 반환합니다. 본문과 raw metadata는 포함하지 않습니다.

### `get_change_detail`

```json
{"change_id": "0198..."}
```

Hermes가 실제 분석 대상으로 선택한 단일 change의 snapshot 본문을 반환합니다.

## 지속 크롤링 흐름

1. Worker가 `FOR UPDATE SKIP LOCKED`와 lease를 사용해 due target을 claim합니다.
2. MonitoringService가 최신 snapshot의 ETag/Last-Modified와 알려진 URL을 준비합니다.
3. 기존 CrawlService가 HTTP 우선, 필요한 경우에만 Browser fallback으로 수집합니다.
4. HTTP 304는 parsing, extractor, hash, Browser fallback을 모두 생략합니다.
5. 추출된 제목·본문·canonical URL을 정규화하고 SHA-256으로 비교합니다.
6. NEW/UPDATED만 새 article/snapshot/change로 저장합니다.
7. UNCHANGED는 snapshot `last_seen_at`만 갱신합니다.
8. target의 다음 실행시간 또는 실패 retry/backoff를 저장하고 lease를 해제합니다.

한 target의 timeout이나 오류는 다른 target 실행을 중단하지 않습니다. Worker 종료 시 SIGINT/SIGTERM을 받아 현재 polling loop를 정리하고 Browser/PostgreSQL lifecycle을 닫습니다.

## PostgreSQL schema

- `article`: DB 생성 UUIDv7, 수집/작성시간, 제목, 내용, 출처, URL, content hash
- `crawl_targets`: URL, interval, enabled, mode/auth/crawl 옵션, 실행·retry·lease 상태
- `crawl_jobs`: target별 실행 상태와 checked/changed/new/updated/unchanged/failed 집계
- `crawl_job_pages`: job과 deduplicated article version 연결
- `crawl_snapshots`: target/page별 변경 version과 ETag/Last-Modified, last seen
- `crawl_changes`: NEW/UPDATED event와 이전·현재 snapshot 참조
- `crawl_failures`: 페이지별 안전한 실패 정보

`article`, target, snapshot, change ID는 PostgreSQL 18 `DEFAULT uuidv7()`가 생성합니다. Adapter INSERT는 ID를 전달하지 않고 `RETURNING id`로 결과만 받습니다. 동일 URL/content hash article은 재사용되므로 UNCHANGED 실행마다 본문이 중복 저장되지 않습니다.

`DELETED`는 첫 버전에서 저장하지 않습니다. bounded crawl이나 부분 실패로 방문하지 못한 페이지를 실제 삭제로 오판할 수 있기 때문입니다.

## Hermes 사용 방식

권장 흐름은 다음과 같습니다.

1. 최초 한 번 `configure_crawl_target`으로 감시 대상을 등록합니다.
2. 일반적인 주기 실행은 Worker에 맡기고 Hermes가 `crawl_site`를 polling하지 않습니다.
3. 분석이 필요할 때 `get_crawl_status` 또는 `get_recent_changes`를 호출합니다.
4. 관심 있는 change만 `get_change_detail`로 가져와 요약·판단합니다.
5. 긴급 재수집이 필요할 때만 `run_crawl_target`을 호출합니다.

기존 방식은 매 주기마다 Agent 실행, MCP 호출, 전체 CrawlResult context 전송이 발생했습니다. 새 방식은 변경이 없어도 Python Worker와 HTTP 304/작은 DB update만 수행합니다. LLM context에는 작은 change summary만 들어가고 선택한 본문만 상세 조회하므로 호출 횟수와 token 사용량이 함께 감소합니다.

## 향후 분산 확장

현재 scheduler는 단일 Worker polling loop지만 target claim은 PostgreSQL lease와 `SKIP LOCKED`를 사용하므로 여러 Worker가 같은 target을 동시에 실행하지 않습니다. 규모가 커지면 다음 경계만 교체합니다.

- `adapters/worker/scheduler.py`: PostgreSQL polling을 Kafka/queue consumer로 교체
- `TargetRepository.claim_due`: scheduler producer 또는 dispatcher로 이동
- lease 컬럼: queue visibility timeout/heartbeat와 결합
- `MonitoringService`: 그대로 유지하고 idempotency key를 job/target lease에 추가
- `MonitoringUnitOfWork`: outbox table을 추가해 snapshot/change commit과 Kafka publish를 원자화

CrawlerEngine, CrawlService, ChangeDetector, MCP query adapter는 분산 Worker 전환 시 변경하지 않습니다.

## 인증 프로필 등록

`config/auth_profiles.yaml`에는 secret이 아닌 참조만 저장합니다.

```yaml
profiles:
  example-reader:
    domain: example.com
    adapter: example_login
    username_env: EXAMPLE_USERNAME
    password_env: EXAMPLE_PASSWORD
    storage_state_path: data/auth/example-reader.json
```

`.env` 또는 Secret Provider가 참조된 환경변수를 제공합니다.

```dotenv
EXAMPLE_USERNAME=reader
EXAMPLE_PASSWORD=replace-me
```

MCP 요청으로 사용자명이나 비밀번호를 전달하지 마십시오. storage state 경로는 `data/auth` 아래 JSON 파일만 허용하며 path traversal과 root 탈출을 거부합니다.

## 새 Login Adapter 추가

1. `AuthenticationAdapter` Protocol의 `is_authenticated`와 `authenticate`를 구현합니다.
2. role, label, placeholder, 안정된 name/id/data-testid, CSS 순으로 Locator 후보를 둡니다.
3. 후보는 count 1, visible, enabled 조건을 모두 확인합니다.
4. 클릭 완료가 아니라 보호 URL, 로그아웃 버튼, 프로필 또는 인증 API로 성공을 검증합니다.
5. `bootstrap.py`의 `AuthRegistry`에 exact domain과 Adapter를 등록합니다.
6. profile YAML에는 secret 값 대신 환경변수 이름만 추가합니다.
7. 로그인, 저장 세션 재사용, 만료 후 재로그인, locator 변경 실패 테스트를 추가합니다.

`ExampleLoginAdapter`가 이 흐름의 실행 가능한 예제입니다.

## 새 Extractor 추가

1. `PageExtractor` Protocol의 `name`과 비동기 `extract`를 구현합니다.
2. engine-neutral `PageSnapshot`에서 `PageItem` 목록을 반환합니다.
3. `bootstrap.py`의 `ExtractorRegistry`에 domain과 함께 등록합니다.
4. 필요하면 `PageRouter` 또는 사이트 classifier로 `START`, `LIST`, `DETAIL`을 구분합니다.
5. 실제 HTML fixture로 제거 태그, 메타데이터, 구조화 필드를 테스트합니다.

미등록 공개 사이트는 `GenericExtractor`를 사용합니다. 인증 profile이 지정된 미등록 사이트는 명확한 `UNSUPPORTED_SITE` 오류를 반환합니다.

## 테스트와 품질 검사

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run pytest -m integration
CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 uv run pytest -m integration tests/integration/test_postgres_monitoring.py
```

기본 pytest는 빠른 단위 테스트만 실행합니다. `integration` marker는 로컬 FastAPI 포트와 Chromium을 사용하며 공개 수집, 인증, storage-state 재사용, 만료 후 재로그인, 목록·상세 탐색, 실패 처리를 검증합니다.

## 실패 파일

브라우저 navigation 또는 extraction 실패 시 가능한 범위에서 다음을 저장합니다.

```text
data/failures/{job_id}/
├── error.json
├── page.html
├── screenshot.png
└── accessibility_snapshot.txt
```

`error.json`은 traceback을 포함하지 않으며 민감 key를 재귀적으로 마스킹합니다. HTML의 password/token input value도 저장 전에 제거합니다. 아티팩트 저장 실패는 원래 도메인 오류를 덮어쓰지 않습니다.

## 보안

- HTTP/HTTPS만 허용하며 URL user-info, file, ftp, data scheme을 거부합니다.
- hostname을 IDNA로 정규화한 뒤 모든 A/AAAA 응답을 검사합니다.
- loopback, private, link-local, unspecified, multicast, reserved 및 metadata IP를 기본 차단합니다.
- DNS 응답 중 하나라도 차단 주소면 전체 요청을 거부합니다.
- 응답 HTML은 운영자 설정 `CRAWLING_MCP_MAX_CONTENT_BYTES` 상한을 넘으면 파싱·추출을 중단합니다.
- 페이지별 발견 링크 수, DNS 답변 수, egress 연결 시간과 연결별 수신 byte에도 운영자 상한을 적용합니다.
- 최초 URL, 발견 링크, navigation 직전과 redirect 최종 URL을 다시 검증합니다.
- HTTP와 Chromium 트래픽은 loopback egress proxy를 통과하며, proxy가 검증된 정확한 IP로 연결합니다. redirect와 iframe·이미지·스크립트 같은 하위 리소스도 같은 정책을 적용받습니다.
- 선택적 domain allowlist는 private-IP 차단을 우회하지 않습니다.
- password, cookie, Authorization, token, storage state는 로그에서 마스킹됩니다.
- robots.txt 준수는 기본 활성화지만 사이트 이용약관과 법적 권한 검토를 대신하지 않습니다.

## 현재 한계

- CAPTCHA, MFA, SSO, device approval을 우회하지 않습니다.
- 임의 사이트 로그인 form을 자동 추측하지 않습니다.
- Adaptive HTTP→browser 전환은 본문 길이·JS shell·login redirect 휴리스틱입니다.
- Browser traversal은 작업별 context 안에서 bounded worker queue를 사용하며 `max_concurrency`, 사이트별 요청 간격, robots.txt를 함께 적용합니다.
- FileRepository는 기존 수동 크롤링용 단일 호스트 Adapter입니다. 지속 Worker는 PostgreSQL을 요구합니다.
- scheduler는 현재 단일 polling 프로세스이며 Kafka/outbox는 아직 포함하지 않습니다.
- 운영 사설망 crawling은 기본 제공하지 않습니다. `allow_private_networks`는 로컬 통합 테스트 또는 격리된 테스트 Compose에서만 사용하십시오.
