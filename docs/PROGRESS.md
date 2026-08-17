# 개발 진행상황

마지막 갱신: 2026-08-17 (Asia/Seoul)

## 현재 상태

- 원격 저장소: `https://github.com/BaektotheFuture98/Crawl_MCP.git`
- 작업 브랜치: `feat/continuous-monitoring`
- 전달 대상: `origin/main`
- migration head: `20260817_03`
- 제품 계약: target 등록 이후 `published_at` 기준 신규 발행 기사만 증분 수집

## 완료된 리팩터링

- `ArticleCrawlState`, content hash, ETag/Last-Modified monitoring cache 제거
- `ArticleChangeDetector`, `ChangeType`, NEW/UPDATED/UNCHANGED 계약 제거
- watermark/lag/overlap 기반 `CollectionWindow`와 `DiscoveryWindowPolicy` 도입
- 글로벌 canonical URL `ARTICLE` 멱등 insert 및 target별 `ARTICLE_DISCOVERY` 기록
- `discovered/inserted/duplicate` run counter와 invariant 도입
- 성공한 현재 lease owner만 run 완료와 watermark 전진 가능
- stale run 복구, heartbeat, retry/backoff, due target `SKIP LOCKED` 유지
- `get_recent_article_changes`를 `get_recent_articles`로 교체
- MCP target 설정에 discovery lag/overlap 노출
- Domain/Application/Adapters/Bootstrap 레이어로 패키지 재배치
- Port를 `application/ports/inbound|outbound`로 이동
- MCP/Worker를 inbound Adapter, Crawlee/PostgreSQL/Auth/Network를 outbound Adapter로 이동
- 모호한 `infrastructure` 및 최상위 `ports` 패키지 제거
- Domain/Application import 방향을 AST 테스트로 강제
- README를 신규 기사 수집, target ID, 로컬/Docker 실행 기준으로 전면 갱신

## 데이터 migration

`20260817_03_article_discovery`가 다음을 수행합니다.

- `article_crawl_state`를 `article_discovery`로 변환하고 기존 target/article 관계 유지
- `first_seen_at`을 `discovered_at`으로 보존
- 기존 run counter 합계를 discovery counter로 backfill
- 기존 target watermark를 알려진 최대 기사 발행시각 또는 최초 발견시각으로 backfill
- downgrade용 구조 복원 제공(과거 change metadata의 의미 복원은 범위 밖)

실제 PostgreSQL 18에서 rev-02 legacy row/run 삽입 후 head upgrade를 수행해 관계, counter,
watermark 보존을 검증했습니다.

## 최신 검증 결과

```text
uv run ruff check .
  passed
uv run ruff format --check .
  passed (139 files)
uv run mypy src/crawling_mcp
  passed (81 source files)
uv run pytest -q
  154 passed, 26 deselected
uv build
  source distribution and wheel built
docker compose config --quiet
  passed
CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 uv run pytest -q -m integration \
  tests/integration/test_postgres_article_discovery.py
  2 passed
```

검증에 사용한 PostgreSQL 컨테이너는 `docker compose down`으로 종료했습니다.

## 주요 문서

- 현재 사용법: `README.md`
- 승인 설계: `docs/superpowers/specs/2026-08-17-article-discovery-refactor-design.md`
- 구현 계획: `docs/superpowers/plans/2026-08-17-article-discovery-refactor.md`
