# Python Crawling MCP

Python Crawling MCP는 MCP Client가 요청한 공개 페이지와 사전에 등록된 인증 사이트를 안전하게 수집하는 STDIO 서버입니다. 임의 사이트의 로그인 방법을 추측하지 않으며, 지원 사이트마다 로그인·세션 검증·페이지 분류·추출 규칙을 Adapter로 등록합니다.

잠금 파일 기준 주요 버전은 Python 3.12, MCP Python SDK 1.29.0, Crawlee 1.9.0, Playwright 1.62.0, Pydantic 2.13.4입니다.

## 아키텍처

```text
FastMCP Adapter
    ↓ 입력 검증, Application Service 호출, 응답 직렬화
CrawlService ── AuthService
    ↓ Protocol ports
CrawlerEngine / AuthenticationAdapter / PageExtractor / CrawlRepository / Network ports
    ↑
Crawlee HTTP / shared Playwright browser / validated egress proxy / registries / storage
```

MCP Tool은 Playwright와 Crawlee를 직접 사용하지 않습니다. `CrawlService`는 Protocol에만 의존하므로 같은 로직을 CLI, REST API 또는 Worker Adapter에서 재사용할 수 있습니다. 서버 lifespan이 Playwright와 Chromium을 한 번 시작하고, 작업별 BrowserContext로 세션을 격리합니다.

## 디렉터리

```text
src/crawling_mcp/
├── domain/           # 모델, enum, 오류, URL·링크 정책
├── application/      # CrawlService, AuthService
├── ports/            # crawler/auth/extractor/repository/browser/network/robots Protocol
├── adapters/
│   ├── mcp/          # 네 MCP Tool
│   ├── crawlee/      # HTTP/browser/adaptive engine, factory, router
│   ├── auth/         # registry, no-auth, saved session, example login
│   ├── extractors/   # generic/example extractor와 registry
│   └── storage/      # memory/file/PostgreSQL repository와 MinIO object store
├── infrastructure/   # 설정, SSRF, egress proxy, robots, logging, browser, artifacts
├── bootstrap.py      # dependency composition root
├── server.py         # FastMCP lifespan
└── test_site.py      # 개발 전용 로그인 사이트
```

인증 storage state는 `data/auth`에 저장됩니다. 운영 크롤링 결과는 PostgreSQL에, 원본 HTML과
실패 아티팩트는 MinIO에 저장되며 Git에서 제외됩니다.

## 로컬 설치와 실행

Python 3.12 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
uv run python -m crawling_mcp
```

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
docker compose build
docker compose run --rm -T mcp-server
```

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

### `scrape_page`

```json
{
  "url": "https://example.com/page",
  "crawl_mode": "auto",
  "auth_profile": null
}
```

성공 결과에는 `url`, `title`, `content`, `metadata`, `meta_description`, `canonical_url`, `language`, `http_status_code`, `published_at`, `source`, `collected_at`이 포함됩니다.

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
```

기본 pytest는 빠른 단위 테스트만 실행합니다. `integration` marker는 로컬 FastAPI 포트와 Chromium을 사용하며 공개 수집, 인증, storage-state 재사용, 만료 후 재로그인, 목록·상세 탐색, 실패 처리를 검증합니다.

PostgreSQL·MinIO 적재 검증은 Compose storage 서비스를 먼저 기동한 뒤 명시적으로 실행합니다.

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml --profile test up -d postgres minio migrate
CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 uv run pytest -m integration tests/integration/test_postgres_minio_storage.py
```

## 실패 파일

`repository=postgres`에서는 브라우저 navigation 또는 extraction 실패 시 가능한 범위에서 다음을
MinIO `jobs/{job_id}/failures/{failure_id}/` prefix에 저장합니다. 실패 응답의 artifact 값은 해당
객체의 `s3://` URI입니다.

```text
jobs/{job_id}/failures/{failure_id}/
├── error.json
├── page.html
├── screenshot.png
└── accessibility_snapshot.txt
```

`error.json`은 traceback을 포함하지 않으며 민감 key를 재귀적으로 마스킹합니다. HTML의 password/token input value도 저장 전에 제거합니다. 아티팩트 저장 실패는 원래 도메인 오류를 덮어쓰지 않습니다.

## PostgreSQL 기사 적재

`repository=postgres`에서 수집 실행은 `crawl_jobs`에, 추출된 기사는 `articles`에 append-only로
저장됩니다. `articles`의 핵심 열은 `collected_at`(수집 시간), `published_at`(기사 작성 시간),
`title`, `content`, `source`, `url`입니다. 같은 URL을 재수집해도 행을 갱신하지 않습니다.

작성 시간과 출처는 JSON-LD, Open Graph, 표준 article metadata를 차례로 해석하며 찾을 수 없으면
`NULL`로 저장합니다. PostgreSQL에는 원본 HTML의 MinIO key·URI·SHA-256·크기를 함께 기록합니다.
스키마는 `alembic upgrade head`로 적용되며 Compose의 `migrate` 서비스가 MCP 서버보다 먼저 이를 수행합니다.

운영에서는 `CRAWLING_MCP_POSTGRES_DSN`, `CRAWLING_MCP_MINIO_ENDPOINT`,
`CRAWLING_MCP_MINIO_ACCESS_KEY`, `CRAWLING_MCP_MINIO_SECRET_KEY`,
`CRAWLING_MCP_MINIO_BUCKET`, `CRAWLING_MCP_MINIO_SECURE`를 Secret Manager 또는 환경변수로 제공합니다.

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
- PostgreSQL repository는 crawl 결과의 영속화만 담당합니다. 대규모 다중 replica 탐색에는 별도 분산 queue와 작업 조정이 필요합니다.
- 운영 사설망 crawling은 기본 제공하지 않습니다. `allow_private_networks`는 로컬 통합 테스트 또는 격리된 테스트 Compose에서만 사용하십시오.
