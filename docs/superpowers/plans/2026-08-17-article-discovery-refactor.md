# Article Discovery Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace article change monitoring with publication-time watermark discovery, reorganize the repository into explicit hexagonal boundaries, document operation, and publish the verified result to GitHub `main`.

**Architecture:** Introduce discovery domain types and storage alongside the current state model, migrate persisted relationships and run counters, then switch collection and MCP contracts before deleting change-oriented code. After behavior is green, move ports and concrete implementations into Application and inbound/outbound Adapter packages, with Bootstrap as the only composition root.

**Tech Stack:** Python 3.12, asyncio, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 18, Alembic, FastMCP, Crawlee, Playwright, pytest, Ruff, mypy, Docker Compose.

## Global Constraints

- Collect only candidates with `start <= published_at < end`.
- Calculate `start = (watermark or created_at) - overlap` and `end = now - lag`.
- Advance the watermark to `end` only in a successful owner-fenced terminal transaction.
- Keep one globally unique normalized `ARTICLE.url` and one discovery per `(target_id, article_id)`.
- Preserve lease heartbeat, stale-owner fencing, stale-run recovery, retry/backoff, SSRF, crawl bounds, authentication, and generic crawl tools.
- Remove change hashes, updated/unchanged semantics, and `get_recent_article_changes` from the final public contract.
- Preserve existing target/article relationships and historical run totals through migration `20260817_03`.
- Domain and Application must not import concrete Adapter or Bootstrap modules.
- Do not overwrite the unrelated `.env.example` change in the primary `main` worktree.

---

### Task 1: Discovery window domain and collection DTOs

**Files:**
- Create: `src/crawling_mcp/domain/collection/__init__.py`
- Create: `src/crawling_mcp/domain/collection/entities.py`
- Create: `src/crawling_mcp/domain/collection/policies.py`
- Modify: `src/crawling_mcp/domain/monitoring.py`
- Modify: `src/crawling_mcp/domain/articles.py`
- Test: `tests/unit/test_collection_domain.py`
- Test: `tests/unit/test_monitoring_models.py`

**Interfaces:**
- Produces: `CollectionWindow(start: datetime, end: datetime)` with `contains(published_at: datetime | None) -> bool`.
- Produces: `DiscoveryWindowPolicy.calculate(target, now) -> CollectionWindow`.
- Produces: `ArticleDiscovery(target_id, article_id, discovered_at)` and `ArticleDiscoveryCreate`.
- Produces: `CollectionResult(target_id, crawl_run_id, visited_pages, discovered_articles, inserted_articles, duplicate_articles, failed_pages)`.
- Produces target fields `discovery_watermark_at`, `discovery_lag_seconds=30`, `discovery_overlap_seconds=300`.

- [ ] **Step 1: Write failing domain tests**

Add tests with aware UTC datetimes that assert overlap/lag boundaries, first-run use of `created_at`, inclusive start, exclusive end, naive publication timestamps normalized as UTC, and rejection of negative lag/overlap.

- [ ] **Step 2: Run domain tests and verify RED**

Run: `uv run pytest tests/unit/test_collection_domain.py tests/unit/test_monitoring_models.py -q`

Expected: imports or fields fail because collection domain types do not exist.

- [ ] **Step 3: Implement minimal domain types**

Use immutable Pydantic models for consistency with the current codebase. `DiscoveryWindowPolicy.calculate` must clamp an inverted first-run window to an empty window whose `start == end`, and `CollectionWindow.contains(None)` must return `False`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/unit/test_collection_domain.py tests/unit/test_monitoring_models.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/crawling_mcp/domain/collection src/crawling_mcp/domain/monitoring.py src/crawling_mcp/domain/articles.py tests/unit/test_collection_domain.py tests/unit/test_monitoring_models.py
git commit -m "feat(domain): model article discovery windows"
```

### Task 2: Discovery persistence schema and data-preserving migration

**Files:**
- Create: `alembic/versions/20260817_03_article_discovery.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/schema.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/mapping.py`
- Create: `src/crawling_mcp/adapters/storage/postgres/discovery_repository.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/article_repository.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/target_repository.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/run_repository.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/unit_of_work.py`
- Modify: `src/crawling_mcp/adapters/storage/monitoring_memory.py`
- Modify: `src/crawling_mcp/ports/monitoring.py`
- Test: `tests/unit/test_migrations.py`
- Test: `tests/unit/test_monitoring_repositories.py`
- Test: `tests/integration/test_postgres_monitoring.py`

**Interfaces:**
- Produces: `ArticleInsertResult(article: Article, inserted: bool)`.
- Produces: `ArticleRepository.insert_or_get(candidate) -> ArticleInsertResult`.
- Produces: `ArticleDiscoveryRepository.record(value: ArticleDiscoveryCreate) -> bool`.
- Produces: `ArticleDiscoveryRepository.list_recent(target_id, limit) -> list[ArticleDiscoverySummary]`.
- Produces: owner-fenced `TargetRepository.mark_succeeded(..., discovery_watermark_at: datetime) -> bool`.
- Produces discovery-oriented run persistence fields and mappings.

- [ ] **Step 1: Write failing schema, repository, and migration tests**

Assert exact target fields, exact `article_discovery` columns, ordered composite primary key, renamed run counters, idempotent discovery recording, and inserted/existing article distinction. Add an integration test that downgrades to revision 02, inserts a state row and a run with new/updated/unchanged counts, upgrades to revision 03, then proves relationship and total preservation.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_migrations.py tests/unit/test_monitoring_repositories.py -q`

With PostgreSQL: `CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 uv run pytest -m integration tests/integration/test_postgres_monitoring.py -q`

- [ ] **Step 3: Implement migration `20260817_03`**

Rename `article_crawl_state` to `article_discovery`, rename `first_seen_at` to `discovered_at`, drop change/cache columns and obsolete indexes, and rename primary/FK constraints. Add target watermark/lag/overlap with non-negative checks. Add/backfill discovery run counters using the formulas in the design, then drop legacy counters. The downgrade recreates legacy columns as nullable/defaulted structural fields and restores legacy counter values deterministically.

- [ ] **Step 4: Implement repositories and UoW contracts**

PostgreSQL article insertion must use `ON CONFLICT (url) DO UPDATE SET url = excluded.url RETURNING` plus an inserted indicator derived from PostgreSQL system metadata or a preceding conflict-safe statement. Discovery record uses `ON CONFLICT (target_id, article_id) DO NOTHING RETURNING`. In-memory behavior must match.

- [ ] **Step 5: Run focused tests and migration round-trip**

Run:

```bash
uv run pytest tests/unit/test_migrations.py tests/unit/test_monitoring_repositories.py tests/unit/test_postgres_repositories.py -q
uv run alembic upgrade head
CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 uv run pytest -m integration tests/integration/test_postgres_monitoring.py -q
```

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/20260817_03_article_discovery.py src/crawling_mcp/adapters/storage src/crawling_mcp/ports/monitoring.py tests/unit/test_migrations.py tests/unit/test_monitoring_repositories.py tests/unit/test_postgres_repositories.py tests/integration/test_postgres_monitoring.py
git commit -m "feat(storage): persist article discoveries"
```

### Task 3: Publication-time ArticleCollectionService

**Files:**
- Create: `src/crawling_mcp/application/article_collection_service.py`
- Modify: `src/crawling_mcp/application/monitoring_service.py`
- Delete: `src/crawling_mcp/application/article_persistence_service.py`
- Delete: `src/crawling_mcp/domain/change_detector.py`
- Modify: `src/crawling_mcp/domain/enums.py`
- Modify: `src/crawling_mcp/domain/models.py`
- Modify: `src/crawling_mcp/adapters/crawlee/http_engine.py`
- Modify: `src/crawling_mcp/application/crawl_service.py`
- Test: `tests/unit/test_article_collection_service.py`
- Modify: `tests/unit/test_monitoring_service.py`
- Delete: `tests/unit/test_article_persistence_service.py`
- Delete: `tests/unit/test_change_detector.py`
- Modify: `tests/unit/test_http_cache.py`
- Modify: `tests/integration/test_public_crawl.py`

**Interfaces:**
- Consumes `DiscoveryWindowPolicy`, `ArticleInsertResult`, discovery repository, and owner-fenced target completion.
- Produces `ArticleCollectionService.run_target(target_id, force=False) -> CollectionResult | None`.
- Produces `ArticleCollectionService.run_due_targets(worker_id, batch_size, lease_seconds) -> list[CollectionResult]`.

- [ ] **Step 1: Write failing service tests**

Cover initial and subsequent windows, inclusive/exclusive publication boundaries, undated skip, duplicate URL reservation, global duplicate counting, idempotent discovery, empty-window advance, failed callback non-advance, lease-loss non-advance, heartbeat failure, stale-run recovery, and just-in-time scheduled claims. Assert `discovered == inserted + duplicate` for every completed run.

- [ ] **Step 2: Run service tests and verify RED**

Run: `uv run pytest tests/unit/test_article_collection_service.py tests/unit/test_monitoring_service.py -q`

- [ ] **Step 3: Implement collection orchestration**

Stream page callbacks without retaining result items. Normalize candidate `published_at` to UTC, filter through the collection window, reserve canonical URLs under an `asyncio.Lock`, persist articles and discoveries immediately, and update counters under a lock. Complete target and run in one owner-fenced UoW with watermark `window.end`.

- [ ] **Step 4: Remove monitoring cache/change behavior**

Stop loading target state validators and remove monitoring use of `CrawlCacheEntry`, ETag, Last-Modified, and not-modified callbacks. Keep ordinary HTTP status handling but remove conditional monitoring tests and change detector code.

- [ ] **Step 5: Run focused and crawler tests**

Run: `uv run pytest tests/unit/test_article_collection_service.py tests/unit/test_monitoring_service.py tests/unit/test_crawl_service.py tests/unit/test_http_cache.py tests/integration/test_public_crawl.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/crawling_mcp/application src/crawling_mcp/domain src/crawling_mcp/adapters/crawlee tests/unit tests/integration/test_public_crawl.py
git commit -m "refactor(collection): collect newly published articles"
```

### Task 4: Discovery query and MCP contract

**Files:**
- Create: `src/crawling_mcp/application/collection_query_service.py`
- Delete: `src/crawling_mcp/application/monitoring_query_service.py`
- Modify: `src/crawling_mcp/adapters/mcp/tools.py`
- Modify: `src/crawling_mcp/bootstrap.py`
- Modify: `src/crawling_mcp/server.py`
- Modify: `tests/unit/test_monitoring_queries.py`
- Modify: `tests/unit/test_mcp_monitoring_tools.py`
- Modify: `tests/unit/test_server.py`
- Modify: `tests/unit/test_bootstrap_monitoring.py`

**Interfaces:**
- Produces `CollectionQueryService.get_recent_articles(target_id, limit) -> list[ArticleDiscoverySummary]`.
- Replaces MCP tool `get_recent_article_changes` with `get_recent_articles`.
- Returns discovery counters from `run_crawl_target` and `get_crawl_status`.

- [ ] **Step 1: Write failing query and MCP tests**

Assert the new tool exists, the old tool is absent, summaries contain article ID/URL/title/publisher/published/discovered timestamps without content, target payloads contain watermark settings, and run payloads contain discovery counters only.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_monitoring_queries.py tests/unit/test_mcp_monitoring_tools.py tests/unit/test_server.py tests/unit/test_bootstrap_monitoring.py -q`

- [ ] **Step 3: Implement query service and tool contract**

Rename monitoring-facing methods to collection terminology, map discovery summaries from joined ARTICLE rows, and update MCP error/log names. Do not retain a compatibility alias for the removed change tool because the approved contract is intentionally breaking.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2.

- [ ] **Step 5: Commit**

```bash
git add src/crawling_mcp/application src/crawling_mcp/adapters/mcp/tools.py src/crawling_mcp/bootstrap.py src/crawling_mcp/server.py tests/unit/test_monitoring_queries.py tests/unit/test_mcp_monitoring_tools.py tests/unit/test_server.py tests/unit/test_bootstrap_monitoring.py
git commit -m "feat(mcp): expose article discovery queries"
```

### Task 5: Move ports into Application and enforce dependency direction

**Files:**
- Create: `src/crawling_mcp/application/ports/inbound/*.py`
- Create: `src/crawling_mcp/application/ports/outbound/*.py`
- Create: `src/crawling_mcp/application/commands/*.py`
- Create: `src/crawling_mcp/application/results/*.py`
- Create: `src/crawling_mcp/application/execution/crawling.py`
- Modify: all files under `src/crawling_mcp/application/`
- Delete: `src/crawling_mcp/ports/*.py`
- Create: `src/crawling_mcp/domain/redaction.py`
- Test: `tests/unit/test_architecture_boundaries.py`

**Interfaces:**
- Produces inbound `McpApplication`, `RunCollectionTargetUseCase`, `RunDueTargetsUseCase`, and generic crawl/auth query protocols.
- Produces outbound repository/UoW, crawler, extractor, auth, browser, network, robots, artifact, and clock protocols.
- Produces pure `mask_sensitive` in Domain so Application no longer imports Bootstrap/Adapters.

- [ ] **Step 1: Write failing import-boundary test**

Parse Application and Domain modules with `ast` and fail when Domain imports Application/Adapters/Bootstrap or Application imports Adapters/Bootstrap. Assert the old top-level `ports` package is absent.

- [ ] **Step 2: Run architecture test and verify RED**

Run: `uv run pytest tests/unit/test_architecture_boundaries.py -q`

- [ ] **Step 3: Create inbound/outbound port modules and update consumers**

Move protocols by responsibility, not by concrete technology name. Move request commands, public results, and internal execution hooks out of broad domain model modules. Replace AuthService concrete `AuthRegistry` and `AuthProfileStore` types with outbound protocols and inject storage-path resolution as a port.

- [ ] **Step 4: Remove old ports and concrete Application imports**

Move redaction to Domain, update every import, delete the old top-level port files, and keep no re-export compatibility package.

- [ ] **Step 5: Run architecture, type, and application tests**

Run:

```bash
uv run pytest tests/unit/test_architecture_boundaries.py tests/unit/test_crawl_service.py tests/unit/test_article_collection_service.py tests/unit/test_monitoring_queries.py -q
uv run mypy src
```

- [ ] **Step 6: Commit**

```bash
git add src/crawling_mcp/application src/crawling_mcp/domain src/crawling_mcp/ports tests/unit/test_architecture_boundaries.py
git commit -m "refactor(core): enforce hexagonal port boundaries"
```

### Task 6: Repackage inbound/outbound adapters and Bootstrap

**Files:**
- Move: `src/crawling_mcp/adapters/mcp/` → `src/crawling_mcp/adapters/inbound/mcp/`
- Move: `src/crawling_mcp/adapters/worker/` → `src/crawling_mcp/adapters/inbound/worker/`
- Move: crawler, extractor, persistence, auth modules → `src/crawling_mcp/adapters/outbound/`
- Move: concrete browser/network/artifact modules from `infrastructure/` → `adapters/outbound/`
- Create: `src/crawling_mcp/bootstrap/container.py`
- Create: `src/crawling_mcp/bootstrap/settings.py`
- Create: `src/crawling_mcp/bootstrap/logging.py`
- Create: `src/crawling_mcp/bootstrap/lifecycle.py`
- Delete: `src/crawling_mcp/bootstrap.py`
- Delete: `src/crawling_mcp/infrastructure/`
- Modify: `src/crawling_mcp/__main__.py`
- Modify: `src/crawling_mcp/worker.py`
- Modify: packaging/import tests
- Test: `tests/unit/test_architecture_boundaries.py`
- Test: `tests/unit/test_packaging.py`

**Interfaces:**
- Bootstrap is the sole concrete dependency composition root.
- Inbound adapters consume only inbound ports/commands/results.
- Outbound adapters implement outbound ports and may depend on Domain.

- [ ] **Step 1: Extend failing architecture and packaging tests**

Assert expected final package roots, absence of `infrastructure` and module-form `bootstrap.py`, inbound adapter imports do not reference outbound concrete packages, and all production modules import successfully.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_architecture_boundaries.py tests/unit/test_packaging.py -q`

- [ ] **Step 3: Move adapter packages and update imports**

Use `git mv` to preserve history. Keep crawling navigation close to crawling engines, generic and article extractors under outbound extraction, all repositories under outbound persistence, and runtime security/network implementations under outbound network.

- [ ] **Step 4: Split Bootstrap and update entry points**

Move settings/logging unchanged first, move lifecycle ownership out of the former application façade, then construct an inbound application façade from explicit use cases in `container.py`. Update server and worker entry points.

- [ ] **Step 5: Run full unit suite and type checks**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -m 'not integration' -q`

- [ ] **Step 6: Commit**

```bash
git add src tests
git commit -m "refactor(layout): separate inbound and outbound adapters"
```

### Task 7: README, full verification, and GitHub main delivery

**Files:**
- Modify: `README.md`
- Modify: `docs/PROGRESS.md`
- Modify: `docker-compose.yml` and `.env.example` only if new target defaults require configuration

**Interfaces:**
- Documents exact commands and MCP JSON examples for the final implementation.
- Produces a verified GitHub `main` pointing at the final commit.

- [ ] **Step 1: Update README usage and architecture**

Document local `uv` setup, Playwright installation, PostgreSQL migration, MCP start, worker start, Docker start/stop, target configuration including lag/overlap, manual execution, status query, recent article query, article detail query, new-only semantics, missing-date limitation, and test commands. Ensure examples match actual Pydantic/MCP field names.

- [ ] **Step 2: Update progress evidence**

Record current branch/commit, migration head, unit/integration counts, and the final architecture. Do not copy stale historical counts.

- [ ] **Step 3: Run all verification gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
docker compose up -d postgres
uv run alembic upgrade head
CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 uv run pytest -m integration -q
docker compose down
git diff --check
```

- [ ] **Step 4: Audit removal and public contract**

Run searches proving no production references remain to `ArticleCrawlState`, `ArticleChangeDetector`, `ChangeType`, `get_recent_article_changes`, `updated_articles`, `unchanged_articles`, `crawling_mcp.infrastructure`, or the top-level `crawling_mcp.ports` package. Verify `get_recent_articles`, discovery counters, watermark fields, and README examples exist.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md docs/PROGRESS.md docker-compose.yml
git add .env.example  # only when this task intentionally changed it in the isolated worktree
git commit -m "docs: document incremental article discovery"
```

- [ ] **Step 6: Push verified head to GitHub main**

Confirm the remote `main` SHA before push and require a fast-forward update. Push with:

```bash
git push origin HEAD:refs/heads/main
```

Then compare `git rev-parse HEAD` with `git ls-remote --heads origin main` and report the matching SHA.
