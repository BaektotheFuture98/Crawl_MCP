# Crawl MCP

등록한 뉴스 사이트에서 **등록 이후 새로 발행된 기사만** 주기적으로 수집해 PostgreSQL
`ARTICLE` 테이블에 저장하는 Python MCP 서버입니다. MCP 서버는 명령·조회 인터페이스를,
별도 Worker는 반복 실행을 담당합니다.

메인 서버는 FastAPI REST 서버가 아니라 MCP Python SDK의 `FastMCP`로 만든 **STDIO MCP
서버**입니다. FastAPI는 로컬 인증 통합 테스트용 `test_site`에만 사용합니다.

## 수집 계약

- 기준은 기사 수정 시각이 아니라 `published_at`입니다.
- target 등록 이전의 과거 기사 전체를 backfill하지 않습니다.
- `start <= published_at < end`인 기사만 수집합니다.
- `published_at`이 없거나 timezone offset이 없는 후보는 신뢰할 수 없는 시각으로 보고
  저장하지 않습니다.
- canonical URL이 같은 기사는 전체 target에서 하나의 `ARTICLE`만 사용합니다.
- 이미 저장된 URL을 다시 보더라도 기사 본문을 수정하지 않습니다.
- `(target_id, article_id)` 관계는 `ARTICLE_DISCOVERY`에 한 번만 기록합니다.

수집 구간은 다음과 같습니다.

```text
base  = discovery_watermark_at 또는 target.created_at
start = base - discovery_overlap_seconds
end   = 현재 시각 - discovery_lag_seconds
```

기본 lag는 30초, overlap은 300초입니다. lag는 게시 시스템과 수집기 사이의 시계 차이를
흡수하고, overlap은 늦게 노출된 기사를 다시 확인합니다. URL 및 발견 관계가 멱등이므로
overlap 구간을 다시 읽어도 중복 행은 생기지 않습니다. watermark는 성공한 실행에서만
전진합니다.

## 아키텍처

레이어 기반 헥사고날 구조입니다. 의존 방향은 안쪽을 향합니다.

```text
Adapters Inbound                   Bootstrap
  FastMCP / Worker                    composition, config, logging
          │                                      │
          ▼                                      ▼
Application ── inbound/outbound ports ── Adapters Outbound
  CrawlService                         Crawlee / extraction / auth
  ArticleCollectionService            PostgreSQL / browser / network
  CollectionQueryService              artifacts
          │
          ▼
Domain
  article / collection window / target / run / policies / errors
```

```text
src/crawling_mcp/
├── domain/
├── application/
│   ├── article_collection_service.py
│   ├── collection_query_service.py
│   └── ports/
│       ├── inbound/
│       └── outbound/
├── adapters/
│   ├── inbound/
│   │   ├── mcp/
│   │   └── worker/
│   └── outbound/
│       ├── authentication/
│       ├── crawling/
│       ├── extraction/
│       ├── network/
│       └── persistence/
└── bootstrap/
    ├── composition.py
    ├── config.py
    └── logging.py
```

Domain은 Application, Adapter, Bootstrap을 참조하지 않고 Application은 Adapter와
Bootstrap을 참조하지 않습니다. 이 규칙은 테스트에서 AST 기반으로 검사합니다.

## 요구 사항

- Python 3.12 이상
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop 또는 호환 Docker Engine
- Chromium을 사용하는 사이트라면 Playwright browser

## 가장 빠른 로컬 실행

### 1. 의존성 설치

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

`.env.example`은 로컬 PostgreSQL 포트 `54329`와 `repository=postgres`가 설정돼 있습니다.

### 2. PostgreSQL 시작 및 migration

```bash
docker compose up -d postgres
uv run alembic upgrade head
```

### 3. MCP 서버 시작

```bash
uv run python -m crawling_mcp
```

서버는 STDIO를 MCP protocol 전용으로 사용하고 로그는 stderr로 출력합니다. 일반적인
HTTP URL에 `curl`을 보내는 방식으로 호출하지 않습니다.

### 4. Worker 시작

새 터미널에서 실행합니다.

```bash
uv run python -m crawling_mcp.worker
```

Worker가 due target을 claim하고 주기적으로 실행합니다. Worker는 MCP 서버를 다시 호출하지
않고 동일한 Application use case를 직접 실행합니다.

### 5. 종료

MCP 서버와 Worker를 `Ctrl-C`로 종료한 뒤 PostgreSQL도 내립니다.

```bash
docker compose down
```

DB 데이터까지 제거하려는 경우에만 `docker compose down -v`를 사용하십시오. `-v`는
PostgreSQL named volume을 삭제하므로 복구가 필요하면 사용하면 안 됩니다.

## MCP Client 연결

Codex나 Claude Desktop 같은 STDIO MCP Client에는 프로젝트 절대 경로를 설정합니다.

```json
{
  "mcpServers": {
    "crawl-mcp": {
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

PostgreSQL과 migration은 서버 연결 전에 준비돼 있어야 합니다. 자동 수집까지 필요하면
Worker도 별도로 실행해야 합니다.

## 사용 예: 뉴스 사이트 target 등록

아래는 `https://www.donga.com/news`를 예로 든 요청입니다. 실제 수집 권한, robots.txt,
사이트 이용약관을 먼저 확인해야 합니다. 사이트 HTML이나 JSON-LD에 timezone offset을
포함한 유효한 발행 시각이 없으면 해당 후보는 저장되지 않습니다.

### 1. target 생성

`configure_crawl_target`:

```json
{
  "url": "https://www.donga.com/news",
  "interval_seconds": 300,
  "enabled": true,
  "crawl_mode": "auto",
  "max_pages": 20,
  "max_depth": 2,
  "discovery_lag_seconds": 30,
  "discovery_overlap_seconds": 300
}
```

응답의 `id`가 이후 요청에서 사용하는 **target_id**입니다. PostgreSQL이 생성하는 UUIDv7이며
기사 ID가 아닙니다. 잊어버렸다면 `list_crawl_targets`로 다시 확인할 수 있습니다.

### 2. 즉시 한 번 실행

`run_crawl_target`:

```json
{"target_id": "019c..."}
```

응답 예시:

```json
{
  "target_id": "019c...",
  "crawl_run_id": "019c...",
  "visited_pages": 12,
  "discovered_articles": 3,
  "inserted_articles": 2,
  "duplicate_articles": 1,
  "failed_pages": 0
}
```

항상 `discovered_articles = inserted_articles + duplicate_articles`입니다. 수동 실행도 target
lease를 사용하므로 Worker와 동시에 같은 target을 중복 실행하지 않습니다.

### 3. 최근 발견 기사 조회

`get_recent_articles`:

```json
{"target_id": "019c...", "limit": 20}
```

이 응답은 `article_id`, URL, 제목, 발행사, `published_at`, `discovered_at`만 반환하며 본문은
포함하지 않습니다.

### 4. 선택한 기사 본문 조회

`get_article`:

```json
{"article_id": "019c..."}
```

이때만 `ar_content`를 반환합니다.

## MCP tools

### 범용 수집

- `scrape_page`: 페이지 한 건 수집
- `crawl_site`: 제한된 깊이와 페이지 수로 사이트 탐색
- `validate_session`: 저장된 인증 session 검사
- `list_supported_sites`: 등록된 인증/추출 Adapter 메타데이터 조회

### 신규 기사 수집

- `configure_crawl_target`: target 생성 또는 일부 설정 변경
- `list_crawl_targets`: target ID, 설정, schedule, watermark 조회
- `run_crawl_target`: target 즉시 실행
- `get_crawl_status`: 최근 실행 및 discovery counter 조회
- `get_recent_articles`: 최근 target/article 발견 관계 조회
- `get_article`: 선택한 기사 한 건의 전체 본문 조회

## 동작 과정

1. Worker가 `FOR UPDATE SKIP LOCKED`로 due target 한 건을 claim합니다.
2. 이전 Worker가 남긴 `RUNNING` 기록을 `lease_expired`로 정리합니다.
3. target watermark, lag, overlap으로 이번 `CollectionWindow`를 계산합니다.
4. 실행 중 lease를 주기의 약 1/3 간격으로 갱신합니다.
5. `CrawlService`가 HTTP를 우선 사용하고 필요할 때 Playwright로 fallback합니다.
6. `ArticleExtractor`가 JSON-LD, OpenGraph, semantic article에서 후보를 추출합니다.
7. `published_at`이 윈도우 밖이거나 timezone이 없으면 건너뜁니다.
8. URL을 정규화하고 `ARTICLE`을 conflict-safe insert합니다.
9. `(target_id, article_id)`를 `ARTICLE_DISCOVERY`에 멱등 기록합니다.
10. 현재 lease owner만 `CRAWL_RUN` 완료와 watermark 전진을 commit할 수 있습니다.
11. 실패하면 watermark는 유지하고 exponential backoff 시각을 저장합니다.

한 target의 실패는 다음 target 실행을 중단하지 않습니다. lease를 잃은 오래된 Worker는 새
소유자의 run이나 watermark를 완료 처리할 수 없습니다.

## PostgreSQL schema

- `ARTICLE`: 기존 최종 기사 계약. `id`, `ar_title`, `ar_content`, `reporter`, `publisher`,
  `url`, `published_at`
- `CRAWL_TARGET`: URL, 주기, crawl 옵션, retry/lease, discovery watermark/lag/overlap
- `ARTICLE_DISCOVERY`: `(target_id, article_id)` 복합 PK와 `discovered_at`
- `CRAWL_RUN`: status, visited/discovered/inserted/duplicate/failed counter와 실행 시각

`ARTICLE`, `CRAWL_TARGET`, `CRAWL_RUN` ID는 PostgreSQL 18의 `DEFAULT uuidv7()`가 만듭니다.
Migration은 기존 `ARTICLE`을 생성하거나 삭제하지 않습니다. `20260817_03`은 기존
`ARTICLE_CRAWL_STATE` 관계를 `ARTICLE_DISCOVERY`로 변환하고 이전 run counter를 보존해
backfill합니다.

## Docker 전체 실행

```bash
cp .env.example .env
docker compose up -d
docker compose ps
```

Compose는 PostgreSQL → migration → MCP server/Worker 순으로 시작합니다. MCP server는
STDIO 서비스이므로 대화형 확인이 필요하면 다음처럼 실행할 수 있습니다.

```bash
docker compose run --rm -T mcp-server
```

개발용 인증 test site는 명시적인 test profile에서만 시작합니다.

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml \
  --profile test up -d test-site
```

## 인증 프로필

`config/auth_profiles.yaml`에는 secret 값이 아닌 환경변수 참조만 둡니다.

```yaml
profiles:
  example-reader:
    domain: example.com
    adapter: example_login
    username_env: EXAMPLE_USERNAME
    password_env: EXAMPLE_PASSWORD
    storage_state_path: data/auth/example-reader.json
```

```dotenv
EXAMPLE_USERNAME=reader
EXAMPLE_PASSWORD=replace-me
```

사용자명이나 비밀번호를 MCP 요청으로 전달하지 마십시오. storage state는 지정된 auth root
아래 JSON만 허용하며 path traversal을 거부합니다.

## 새 사이트 Adapter 추가

기사 추출 규칙이 사이트마다 다르면
`adapters/outbound/extraction/articles/`에 `ArticleExtractor` 구현을 추가하고
`bootstrap/composition.py`의 registry에 exact domain으로 등록합니다. 로그인 사이트라면
`adapters/outbound/authentication/`에 `AuthenticationAdapter`도 추가합니다.

Application use case나 MCP Adapter에 사이트별 selector를 넣지 않습니다.

## 테스트와 품질 검사

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/crawling_mcp
uv run pytest
```

PostgreSQL migration과 저장소 통합 테스트:

```bash
docker compose up -d postgres
uv run alembic upgrade head
CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 \
  uv run pytest -q -m integration tests/integration/test_postgres_article_discovery.py
docker compose down
```

전체 integration marker는 로컬 test site와 Chromium을 사용할 수 있습니다.

```bash
uv run pytest -m integration
```

## 보안 및 제한

- HTTP/HTTPS만 허용하고 URL user-info 및 위험 scheme을 거부합니다.
- DNS의 모든 A/AAAA 응답을 검사하고 private, loopback, link-local, metadata IP를 기본
  차단합니다.
- HTTP와 Chromium 트래픽은 검증된 egress 경로를 사용합니다.
- 응답 크기, 링크 수, 요청 시간, 재시도, 전체 job 시간, 동시성을 제한합니다.
- password, cookie, Authorization, token, storage state는 로그와 실패 artifact에서
  마스킹합니다.
- robots.txt 준수는 기본값이지만 법적 권한이나 사이트 이용약관 검토를 대신하지 않습니다.
- CAPTCHA, MFA, SSO, device approval을 우회하지 않습니다.
- 과거 기사 backfill, 기사 수정 감지, 삭제 감지, snapshot/history, Kafka/outbox는 현재 범위에
  포함하지 않습니다.
