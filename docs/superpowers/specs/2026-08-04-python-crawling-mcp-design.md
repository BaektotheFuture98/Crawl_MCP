# Python Crawling MCP Server Design

## 1. 목적과 범위

이 프로젝트는 MCP Client가 URL과 제한 조건을 전달하면 공개 페이지 또는 사전에 등록된 인증 사이트를 안전하게 수집하는 Python 3.12+ 서버를 제공한다. 임의 사이트의 로그인 흐름을 추측하지 않는다. 인증, 페이지 유형 판별, 데이터 추출, 링크 탐색 규칙은 지원 사이트별 Adapter로 명시적으로 등록한다.

완성 범위는 다음 네 개의 실행 가능한 단계로 나눈다.

1. 안전한 URL 검증과 공개 단일 페이지 수집
2. 제한된 사이트 탐색, Crawlee Router, 결과 저장소
3. 인증 Adapter, Playwright storage state, 로컬 로그인 테스트 사이트
4. 실패 아티팩트, 구조화 오류, Docker, 통합 테스트, 운영 문서

프로젝트 루트는 `/Users/seonminbaek/openup/mcp_crawl/python-crawling-mcp`이다.

## 2. 확정 기술과 버전 정책

- Python: `>=3.12,<3.15`
- MCP Python SDK: `mcp>=1.28.1,<2`
- Crawlee for Python: `crawlee[beautifulsoup,playwright]>=1.8.3,<2`
- Playwright for Python: `playwright>=1.61.0,<2`
- Pydantic v2와 pydantic-settings
- asyncio, structlog, pytest, pytest-asyncio, Ruff, mypy
- uv 기반 의존성 잠금과 실행
- FastAPI/Uvicorn 기반 로컬 테스트 사이트
- Playwright Chromium 호환 Docker 이미지

MCP SDK v1은 현재 안정 릴리스이며 v2는 prerelease이므로 `<2` 상한을 둔다. 버전 근거는 공식 패키지 페이지에서 확인한다.

- <https://pypi.org/project/mcp/>
- <https://pypi.org/project/crawlee/>
- <https://pypi.org/project/playwright/>

## 3. 실행 경계와 아키텍처

의존 방향은 항상 바깥 Adapter에서 안쪽 Domain/Port로 향한다.

```text
MCP Adapter
    │ Pydantic 입력 검증, Application Service 호출, 응답 변환
    ▼
Application Services
    │ CrawlService가 실행 순서, AuthService가 인증 상태 전이를 제어
    ▼
Domain Models and Ports
    ▲
    ├── Crawlee engines and router
    ├── Playwright browser/auth adapters
    ├── extractor adapters
    ├── repository adapters
    └── security, configuration, logging infrastructure
```

MCP Tool은 Playwright, Crawlee, 파일 저장소를 직접 import하지 않는다. `CrawlService`는 Protocol 타입에만 의존한다. 같은 Application Service를 향후 CLI, REST API, Worker에서 그대로 호출할 수 있다.

전역 mutable state는 두지 않는다. 서버 lifespan에서 `ApplicationContainer`를 구성하고 종료한다. 이 컨테이너는 설정, Repository, BrowserManager, Auth Registry, Extractor Registry, Crawler Factory, AuthService, CrawlService를 소유한다.

## 4. 디렉터리와 책임

요청에서 지정한 `src/crawling_mcp` 구조를 유지하면서 책임을 다음처럼 나눈다.

- `domain`: 순수 모델, enum, 도메인 오류, URL/탐색 정책
- `ports`: crawler, auth, extractor, repository, browser context에 대한 Protocol
- `application`: crawl orchestration과 인증 상태 전이
- `adapters/mcp`: MCP Tool과 오류 응답 변환
- `adapters/crawlee`: HTTP, browser, adaptive 전략과 Router
- `adapters/auth`: NoAuth, saved session, example login과 Registry
- `adapters/extractors`: generic/example 추출과 Registry
- `adapters/storage`: in-memory/file Repository
- `infrastructure`: 설정, 구조화 로그, SSRF 보안, 브라우저 lifecycle
- `test_site`: 개발 전용 FastAPI 로그인 사이트
- `tests/unit`: 브라우저와 외부 네트워크 없는 테스트
- `tests/integration`: 로컬 HTTP/Playwright를 사용하는 marker 테스트

## 5. 핵심 도메인 모델

### 입력

`ScrapePageRequest`는 URL, crawl mode, 선택적 auth profile을 가진다. `CrawlRequest`는 시작 URL과 함께 max pages, max depth, retry, timeout, concurrency, same-domain, include/exclude pattern, robots 준수, tracking parameter 제거 설정을 가진다.

보수적인 기본값은 다음과 같다.

- `max_pages=20`
- `max_depth=2`
- `max_request_retries=2`
- `request_timeout_seconds=30`
- `job_timeout_seconds=300`
- `max_concurrency=3`
- `same_domain_only=true`
- `respect_robots_txt=true`

Pydantic `Field(default_factory=list)`를 사용하고 모든 제한값에 상한을 둔다. 크롤링 폭주를 방지하기 위해 설정 상한과 요청 상한 중 작은 값을 적용한다.

### 출력

`PageItem`은 최종 URL, 제목, 본문, metadata, meta description, canonical URL, 언어, HTTP 상태, 수집 시각을 담는다. 사이트 Adapter는 metadata 또는 타입이 지정된 추가 item을 반환할 수 있다.

`CrawlResult`는 job ID, 시작 URL, 방문/성공/실패 개수, items, failures, 시작/완료 시각을 담는다. `CrawlFailure`는 URL, 오류 코드, 사용자 메시지, 안전한 details, artifact 경로를 담는다.

## 6. 크롤링 실행 흐름

### 단일 페이지

1. Pydantic 모델이 입력 제한을 검증한다.
2. SecurityPolicy가 URL을 정규화하고 SSRF 검증을 수행한다.
3. CrawlService가 hostname으로 인증/추출 Adapter를 선택한다.
4. AuthService가 인증 필요 여부와 profile을 확인한다.
5. CrawlerFactory가 `http`, `browser`, `auto` 전략을 선택한다.
6. engine이 navigation 직전과 redirect 후 URL을 다시 검증한다.
7. extractor가 페이지 데이터를 추출한다.
8. Repository가 결과를 저장하고 MCP Adapter가 안전한 응답으로 변환한다.

### 사이트 탐색

1. 시작 URL을 `START`, depth 0으로 queue에 넣는다.
2. Crawlee Router가 Adapter의 page classifier 결과에 따라 `START`, `LIST`, `DETAIL` handler를 실행한다.
3. 발견 링크를 절대 URL로 변환하고 정규화한다.
4. SSRF, same-domain, include/exclude, depth, page budget 정책을 enqueue 전에 적용한다.
5. 정규화 URL의 고유 키로 중복을 제거한다.
6. concurrency 안전한 예약 카운터로 `max_pages`를 넘는 enqueue를 막는다.
7. 각 성공/실패를 Repository에 기록하고 마지막에 집계한다.

`max_pages` 도달은 정상적인 탐색 종료로 기록한다. 요청 자체가 설정 상한을 넘거나 내부 정책을 위반하면 `CrawlLimitExceededError`를 반환한다.

## 7. Strategy와 Factory

`CrawlerEngine` Protocol은 단일 페이지와 사이트 탐색에서 공통으로 사용할 비동기 실행 계약을 제공한다.

- HTTP engine: Crawlee의 정적 HTML crawler와 GenericExtractor를 사용한다.
- Browser engine: 공유 Browser 프로세스에서 작업별 BrowserContext를 만들고 Playwright 기반 Crawlee 처리를 수행한다.
- Adaptive engine: 공개 페이지를 HTTP로 시도하고 JavaScript shell, 인증 redirect, 비정상적으로 빈 본문, 동적 페이지 신호가 있을 때 browser engine으로 한 번 전환한다.

인증 profile이 지정된 요청은 storage state의 쿠키/localStorage 일관성을 보장하기 위해 browser engine을 사용한다. `crawl_mode=http`와 인증 profile을 동시에 지정하면 묵시적으로 인증을 생략하지 않고 명확한 validation/domain 오류를 반환한다.

Factory는 enum을 engine 인스턴스로 매핑할 뿐이며 작업별 상태를 보관하지 않는다.

## 8. 인증과 세션

인증 profile은 `config/auth_profiles.yaml`에 저장한다. YAML에는 domain, adapter name, username/password 환경변수 이름, storage state 경로만 기록한다. 실제 secret은 `.env` 또는 실행 환경에서 pydantic-settings가 읽으며 MCP 입력에는 포함하지 않는다.

인증 상태 전이는 다음과 같다.

1. profile이 없으면 도메인의 NoAuth 가능 여부를 확인한다.
2. profile이 있으면 domain 일치와 안전한 storage path를 검증한다.
3. storage state 파일이 있으면 새 BrowserContext에 로드한다.
4. 사이트 Adapter의 `is_authenticated`가 실제 보호 페이지 또는 인증 표식을 확인한다.
5. 유효하면 context를 그대로 사용한다.
6. 만료됐으면 환경변수 Secret을 읽어 `authenticate`를 실행한다.
7. 클릭 성공이 아니라 Adapter의 로그인 성공 조건을 확인한다.
8. 성공한 context의 storage state를 임시 파일에 기록한 뒤 atomic replace한다.

저장 경로는 반드시 설정된 auth root 아래의 `{auth_profile}.json`이어야 한다. path traversal, symlink 탈출, 임의 절대 경로를 거부한다.

예제 로그인 Adapter는 role, label, placeholder, 안정된 attribute, CSS 순으로 후보 Locator를 검사한다. 각 후보는 count가 1인지, visible인지, enabled인지 확인한다. 로그인 성공은 보호 페이지 URL, 사용자 표식, 세션 쿠키 중 사이트에서 정의한 복수 신호로 검증한다.

## 9. Registry와 미지원 사이트 정책

Auth Registry와 Extractor Registry는 정규화한 소문자 hostname을 key로 사용한다. exact domain을 우선하고 명시적으로 등록된 subdomain 규칙만 허용한다.

- 인증 profile이 없는 미등록 domain: `NoAuthAdapter + GenericExtractor`
- 인증 profile이 있는 미등록 domain: `UnsupportedSiteError`
- profile domain과 요청 domain 불일치: `AuthenticationRequiredError` 계열의 안전한 구성 오류
- 등록 domain의 extractor 부재: GenericExtractor fallback 가능 여부를 registry metadata로 결정

`list_supported_sites`는 Registry의 immutable snapshot을 반환하며 secret이나 storage path를 노출하지 않는다.

## 10. URL 정규화와 SSRF 방어

허용 scheme은 `http`, `https`뿐이다. 사용자 정보가 포함된 URL, hostname이 없는 URL, 잘못된 port와 제어 문자가 있는 URL을 거부한다.

URL 검증 순서는 다음과 같다.

1. URL parse 및 canonical representation 생성
2. scheme/hostname/port 검증
3. IDNA hostname 정규화
4. optional domain allowlist 검사
5. 비동기 DNS 조회
6. 반환된 모든 IPv4/IPv6 주소 검사
7. 요청 직전 재검증
8. redirect 대상마다 동일 절차 반복

loopback, unspecified, private, link-local, multicast, reserved IP와 알려진 metadata 주소를 차단한다. `localhost`와 이를 변형한 hostname도 차단한다. DNS 결과 중 하나라도 금지 주소이면 전체 URL을 차단한다.

정규화는 fragment를 제거하고 host/scheme 대소문자를 정리하며 default port를 제거한다. 설정이 활성화되면 `utm_*`, `gclid`, `fbclid` 등 추적 query parameter만 제거한다. 나머지 query 순서는 안정적으로 정렬한다.

로컬 통합 테스트는 별도의 test settings fixture에서만 `allow_private_networks=true`를 주입한다. `.env.example`과 운영 Docker 기본값은 false이다. allowlist는 private-network 차단을 자동 우회하지 않는다.

## 11. 추출

GenericExtractor는 `script`, `style`, `noscript`, `nav`, `footer`를 제거한 DOM에서 공백을 정규화해 본문을 만든다. 최종 URL, title, meta description, canonical, html lang, collected time, HTTP status를 반환한다.

HTTP extractor context와 browser extractor context는 공통 read-only page interface로 감싼다. 사이트 전용 Extractor가 특정 엔진 구현에 직접 결합돼야 하는 경우 별도 capability를 명시하고 Registry가 호환 engine을 요구한다.

예제 Extractor는 목록/상세 페이지 유형을 판별하고 상세 페이지에서 item ID, name, description을 구조화한다.

## 12. Repository

Repository Protocol은 job 시작, page 성공, page 실패, job 완료, 결과 조회, 인증 메타데이터 조회/저장을 비동기로 정의한다.

- `InMemoryRepository`: lock으로 동시 업데이트를 보호하고 테스트에서 사용한다.
- `FileRepository`: `asyncio.to_thread`로 blocking file I/O를 분리하고 임시 파일 후 `os.replace`로 저장한다.

데이터 layout은 `data/results/{job_id}.json`, `data/failures/{job_id}/...`, `data/auth/{profile}.json`이다. PostgreSQL Adapter는 동일 Protocol을 구현하며 Application 계층 변경이 필요 없다.

## 13. 실패, 오류, 관측성

도메인 오류는 `InvalidUrlError`, `BlockedUrlError`, `UnsupportedSiteError`, `AuthenticationRequiredError`, `AuthenticationFailedError`, `SessionExpiredError`, `NavigationError`, `ExtractionError`, `CrawlLimitExceededError`를 제공한다.

MCP Adapter는 도메인 오류를 `error_code`, 안전한 message, job ID, 허용된 details로 변환한다. traceback, cookie, Authorization header, password, storage state 내용은 반환하지 않는다.

브라우저 단계 실패 시 가능한 범위에서 다음 파일을 저장한다.

```text
data/failures/{job_id}/
├── error.json
├── page.html
├── screenshot.png
└── accessibility_snapshot.txt
```

접근성 진단 텍스트는 비밀번호 입력값과 secret 문자열을 제거한다. 아티팩트 저장 자체가 실패해도 원래 도메인 오류를 덮어쓰지 않고 로그에 보조 오류로 기록한다.

structlog processor는 nested mapping/list까지 민감 key를 마스킹한다. 로그 context는 job ID, URL, domain, adapter name을 포함한다. URL user-info와 민감 query parameter도 마스킹한다.

## 14. 브라우저 lifecycle

서버 lifespan에서 Playwright와 Chromium Browser를 한 번 시작한다. 각 작업은 독립 BrowserContext와 Page를 사용한다. profile이 있으면 검증된 storage state를 context 생성 때 로드한다.

작업 종료는 `try/finally` 또는 async context manager로 Page와 BrowserContext를 닫는다. 서버 종료 시 진행 작업을 정리한 뒤 Browser, Playwright 순서로 종료한다. 동시 BrowserContext 수는 전역 semaphore와 요청의 `max_concurrency` 중 작은 값으로 제한한다.

## 15. MCP Tools

- `scrape_page`: Pydantic 입력을 `CrawlService.scrape_page`에 전달하고 PageItem을 반환한다.
- `crawl_site`: `CrawlService.crawl_site`를 호출해 CrawlResult를 반환한다.
- `validate_session`: profile lookup 후 AuthService의 격리된 context 검증 결과를 반환한다.
- `list_supported_sites`: 두 Registry의 metadata를 결합한 snapshot을 반환한다.

MCP 서버는 FastMCP STDIO로 실행한다. `python -m crawling_mcp`가 entry point이며 stdout에는 protocol frame 외의 로그를 쓰지 않는다. 로그는 stderr로 출력한다.

## 16. 로컬 테스트 사이트

FastAPI 앱은 `/test-site/login`, `/test-site/list`, `/test-site/detail/1`, `/test-site/detail/2`를 제공한다. 개발 계정은 `test-user`/`test-password`이며 운영 credential과 분리된 이름과 문서를 사용한다.

로그인 성공 시 서명된 개발용 session cookie를 발급한다. 목록과 상세는 유효 세션이 없으면 login으로 redirect한다. 테스트 fixture는 세션을 만료시키고 로그인 횟수를 조회할 수 있으나 이 진단 endpoint는 test app에서만 존재한다.

로그인 form은 accessible label과 안정 attribute를 제공한다. 별도 variant query/fixture로 label 일부를 바꿔 fallback locator를 검증하고, 모든 후보를 제거한 variant로 실패 아티팩트를 검증한다.

## 17. 테스트 계획과 단계별 품질 게이트

모든 production behavior는 실패하는 테스트를 먼저 실행한 뒤 구현한다.

단위 테스트는 URL 정규화, SSRF와 DNS 결과, pattern 정책, Factory, Registry, profile lookup, storage path, CrawlRequest limits, 두 Repository, nested secret masking을 포함한다.

통합 테스트는 공개 페이지, 로그인 보호 페이지, storage state 재사용, 세션 만료 후 재로그인, 목록-상세 탐색, max pages/depth, 잘못된 secret, locator 부재, 실패 파일 저장을 포함한다. Playwright 테스트에는 `integration` marker를 붙인다.

각 단계 종료 시 다음 전체 gate를 실행한다.

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

브라우저 통합 gate는 별도로 `uv run pytest -m integration`을 실행한다.

## 18. Docker와 배포

Dockerfile은 Playwright 1.61 Chromium 의존성이 일치하는 기반을 사용한다. uv로 locked dependency를 설치하고 애플리케이션 파일을 복사한 뒤 비-root 사용자로 실행한다. Chromium sandbox/권한과 writable data directory를 명시적으로 구성한다.

Compose는 MCP 서버와 test-site 서비스를 분리한다. MCP는 `.env`, profile config, auth/results/failures/screenshots volume을 사용한다. test-site는 개발 profile에서만 기동한다. STDIO MCP가 Compose attach 환경에서 동작하도록 stdin/stdout을 유지하며 README에 로컬 STDIO를 기본 연결 방법으로 제시한다.

## 19. 문서와 확장 지점

README는 목적, 아키텍처, 디렉터리, uv/Playwright/Docker 실행, MCP client 설정, Tool 요청, Login Adapter와 Extractor 추가, profile 등록, 테스트, 실패 아티팩트, 보안, 한계를 설명한다.

신규 사이트 지원 절차는 다음으로 고정한다.

1. AuthenticationAdapter와 session validation을 구현한다.
2. PageExtractor와 page classifier/link policy를 구현한다.
3. bootstrap에서 domain metadata와 함께 두 Registry에 등록한다.
4. secret 환경변수 이름만 profile YAML에 추가한다.
5. locator fallback, login success, extraction, link scope 테스트를 추가한다.

## 20. 현재 의도된 한계

- CAPTCHA, MFA, SSO, device approval은 자동 우회하지 않는다.
- 임의 사이트의 로그인 form을 추측하지 않는다.
- robots.txt 준수는 기본 활성화지만 사이트 이용약관과 법적 권한 판단을 대신하지 않는다.
- Adaptive engine의 HTTP-to-browser 전환은 휴리스틱이며 사이트 Adapter가 명시적으로 browser를 요구할 수 있다.
- 파일 Repository는 단일 호스트 배포용이다. 다중 replica는 향후 PostgreSQL/분산 queue Adapter가 필요하다.
- 로컬 test setting 외에는 사설망 크롤링을 허용하지 않는다.
