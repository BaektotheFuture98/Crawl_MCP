# Monitoring Reliability Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make continuous monitoring safe under overlapping targets, concurrent workers, long-running crawls, and bounded-memory page processing.

**Architecture:** Preserve the existing ports-and-adapters structure. Extend monitoring repository ports with target-scoped state, idempotent article creation, owner-fenced lease operations, and terminal-run reconciliation; then make `MonitoringService` process page callbacks incrementally while crawler engines suppress unused result items.

**Tech Stack:** Python 3.12, asyncio, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 18, Alembic, Crawlee, Playwright, pytest.

## Global Constraints

- Preserve all existing public MCP tool names and response schemas.
- Keep `ARTICLE` globally unique by canonical URL and database-owned UUIDv7.
- Store validators and observation metadata per `(target_id, article_id)`.
- Never let a stale lease owner finalize target state.
- Monitoring memory must scale with active crawler concurrency, not `max_pages`.
- Every production behavior change follows a failing-test-first cycle.

---

### Task 1: Target-scoped article state and idempotent article creation

**Files:**
- Modify: `src/crawling_mcp/ports/monitoring.py`
- Modify: `src/crawling_mcp/adapters/storage/monitoring_memory.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/article_repository.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/state_repository.py`
- Modify: `src/crawling_mcp/application/article_persistence_service.py`
- Modify: `tests/unit/test_article_persistence_service.py`
- Modify: `tests/unit/test_monitoring_repositories.py`

**Interfaces:**
- Produces: `ArticleRepository.insert_or_get(candidate: ArticleCandidate) -> Article`
- Produces: `ArticleCrawlStateRepository.find_by_url(target_id: UUID, url: str) -> ArticleCrawlState | None`
- Produces: state persistence keyed by `(target_id, article_id)`

- [ ] **Step 1: Write failing overlapping-target tests**

Add a test that creates two targets, persists the same canonical candidate through both, and asserts one global article plus one state per target. Assert each first observation is `ChangeType.NEW` and a later observation for one target does not change the other target's validators.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest tests/unit/test_article_persistence_service.py tests/unit/test_monitoring_repositories.py -q`

Expected: failure because `find_by_url` is not target-scoped and the second observation moves the first state.

- [ ] **Step 3: Change the ports and in-memory adapter**

Replace `insert` with `insert_or_get`, change state lookup to accept `target_id`, and key `_states` by `(target_id, article_id)`. Keep `recent_changes(target_id=...)` behavior unchanged.

- [ ] **Step 4: Change PostgreSQL repositories and persistence service**

Implement article insertion using PostgreSQL `ON CONFLICT (url) DO UPDATE SET url = excluded.url RETURNING article`. Scope state selects and updates by both target and article identity. In `ArticlePersistenceService`, call `insert_or_get` before target-scoped change detection and create `NEW` state for every target's first observation.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `uv run pytest tests/unit/test_article_persistence_service.py tests/unit/test_monitoring_repositories.py tests/unit/test_postgres_repositories.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/crawling_mcp/ports/monitoring.py src/crawling_mcp/adapters/storage/monitoring_memory.py src/crawling_mcp/adapters/storage/postgres/article_repository.py src/crawling_mcp/adapters/storage/postgres/state_repository.py src/crawling_mcp/application/article_persistence_service.py tests/unit/test_article_persistence_service.py tests/unit/test_monitoring_repositories.py tests/unit/test_postgres_repositories.py
git commit -m "fix(monitoring): scope article state by target"
```

### Task 2: Migrate PostgreSQL state identity and verify concurrent upsert

**Files:**
- Create: `alembic/versions/20260817_02_target_scoped_article_state.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/schema.py`
- Modify: `tests/unit/test_migrations.py`
- Modify: `tests/integration/test_postgres_monitoring.py`

**Interfaces:**
- Consumes: target-scoped repository signatures from Task 1
- Produces: primary key `(target_id, article_id)` and unique `(target_id, url)`

- [ ] **Step 1: Write failing migration and PostgreSQL integration tests**

Add assertions for the new revision, composite primary key, target-scoped URL uniqueness, preserved rows, and two concurrent `persist` calls that produce one `ARTICLE` row and two state rows.

- [ ] **Step 2: Run tests and verify RED**

Run unit migration test: `uv run pytest tests/unit/test_migrations.py -q`

Run PostgreSQL integration test when storage is available:
`CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 uv run pytest -m integration tests/integration/test_postgres_monitoring.py -q`

- [ ] **Step 3: Implement the schema and Alembic revision**

Drop the old `article_crawl_state` primary key and global URL unique constraint, create the composite primary key and target-scoped unique constraint, and update SQLAlchemy table metadata. Preserve all existing rows.

- [ ] **Step 4: Run migration and integration tests and verify GREEN**

Run: `uv run pytest tests/unit/test_migrations.py -q`

Run the storage integration command from Step 2.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/20260817_02_target_scoped_article_state.py src/crawling_mcp/adapters/storage/postgres/schema.py tests/unit/test_migrations.py tests/integration/test_postgres_monitoring.py
git commit -m "fix(storage): isolate article state per target"
```

### Task 3: Owner-fenced leases and stale-run recovery

**Files:**
- Modify: `src/crawling_mcp/ports/monitoring.py`
- Modify: `src/crawling_mcp/adapters/storage/monitoring_memory.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/target_repository.py`
- Modify: `src/crawling_mcp/adapters/storage/postgres/run_repository.py`
- Modify: `tests/unit/test_monitoring_repositories.py`
- Modify: `tests/unit/test_postgres_repositories.py`

**Interfaces:**
- Produces: `renew_lease(target_id, lease_owner, now, lease_seconds) -> bool`
- Produces: owner-aware `mark_succeeded(...) -> bool` and `mark_failed(...) -> bool`
- Produces: `CrawlRunRepository.fail_running(target_id, completed_at, error) -> int`
- Produces: `CrawlRunRepository.save_terminal(run) -> bool`

- [ ] **Step 1: Write failing repository contract tests**

Test that owner A cannot renew or finalize after owner B acquires an expired lease. Test that `fail_running` changes only RUNNING rows and that `save_terminal` cannot overwrite a reconciled row.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `uv run pytest tests/unit/test_monitoring_repositories.py tests/unit/test_postgres_repositories.py -q`

- [ ] **Step 3: Implement in-memory and PostgreSQL fencing**

Add lease owner predicates to every renew/finalize update and return success from affected row counts. Add conditional terminal-run updates and stale RUNNING reconciliation.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2.

- [ ] **Step 5: Commit**

```bash
git add src/crawling_mcp/ports/monitoring.py src/crawling_mcp/adapters/storage/monitoring_memory.py src/crawling_mcp/adapters/storage/postgres/target_repository.py src/crawling_mcp/adapters/storage/postgres/run_repository.py tests/unit/test_monitoring_repositories.py tests/unit/test_postgres_repositories.py
git commit -m "fix(worker): fence target leases by owner"
```

### Task 4: Heartbeat long runs and claim scheduled work just in time

**Files:**
- Modify: `src/crawling_mcp/domain/errors.py`
- Modify: `src/crawling_mcp/application/monitoring_service.py`
- Modify: `tests/unit/test_monitoring_service.py`

**Interfaces:**
- Consumes: owner-fenced repository methods from Task 3
- Produces: background lease renewal during a claimed run
- Produces: one-at-a-time scheduled claim loop bounded by `batch_size`

- [ ] **Step 1: Write failing service tests**

Add tests proving a blocked run renews before expiry, lost renewal prevents stale finalization, stale RUNNING runs are reconciled before a new run, and the second scheduled target is not claimed until the first finishes.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_monitoring_service.py -q`

- [ ] **Step 3: Implement heartbeat and just-in-time claims**

Add a `LeaseLostError`, a heartbeat task stopped in `finally`, an immediate owner check before final commit, owner-fenced success/failure handling, stale-run reconciliation, and a loop that calls `claim_due(limit=1)` immediately before each execution.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2.

- [ ] **Step 5: Commit**

```bash
git add src/crawling_mcp/domain/errors.py src/crawling_mcp/application/monitoring_service.py tests/unit/test_monitoring_service.py
git commit -m "fix(worker): renew and fence active target leases"
```

### Task 5: Stream monitoring pages without aggregate item retention

**Files:**
- Modify: `src/crawling_mcp/domain/models.py`
- Modify: `src/crawling_mcp/application/crawl_service.py`
- Modify: `src/crawling_mcp/adapters/crawlee/http_engine.py`
- Modify: `src/crawling_mcp/adapters/crawlee/browser_engine.py`
- Modify: `src/crawling_mcp/application/monitoring_service.py`
- Modify: `tests/unit/test_crawl_service.py`
- Modify: `tests/unit/test_monitoring_service.py`
- Modify: `tests/integration/test_public_crawl.py`

**Interfaces:**
- Produces: `CrawlExecution.collect_items: bool = True`
- Produces: `CrawlContext.collect_items: bool = True`
- Monitoring uses `collect_items=False` and persists inside `page_handler`

- [ ] **Step 1: Write failing crawler and monitoring tests**

Test that callbacks still receive snapshots and items when `collect_items=False`, returned `CrawlResult.items` stays empty, and persistence is complete before the fake runner emits the next page. Assert monitoring no longer keeps snapshot lists.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `uv run pytest tests/unit/test_crawl_service.py tests/unit/test_monitoring_service.py tests/integration/test_public_crawl.py -q`

- [ ] **Step 3: Add collection control to crawler engines**

Propagate `collect_items` through `CrawlExecution` and `CrawlContext`. Guard `result.items.extend(items)` in HTTP and browser engines while leaving public defaults unchanged.

- [ ] **Step 4: Stream extraction and persistence in MonitoringService**

Move article extraction, target-scoped not-modified updates, duplicate URL reservation, persistence, and counters into callbacks. Use an `asyncio.Lock` for reservation and counter updates. Remove retained snapshot lists.

- [ ] **Step 5: Run focused and full tests and verify GREEN**

Run focused command from Step 2, then `uv run pytest -q`.

- [ ] **Step 6: Commit**

```bash
git add src/crawling_mcp/domain/models.py src/crawling_mcp/application/crawl_service.py src/crawling_mcp/adapters/crawlee/http_engine.py src/crawling_mcp/adapters/crawlee/browser_engine.py src/crawling_mcp/application/monitoring_service.py tests/unit/test_crawl_service.py tests/unit/test_monitoring_service.py tests/integration/test_public_crawl.py
git commit -m "refactor(monitoring): process crawl pages incrementally"
```

### Task 6: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/PROGRESS.md`

**Interfaces:**
- Documents: target-scoped state, lease heartbeat/fencing, streaming behavior, recovery semantics

- [ ] **Step 1: Update operational documentation**

Document that article rows are global, observation state is per target, active workers renew leases, stale owners cannot finalize, and monitoring does not retain full crawl results.

- [ ] **Step 2: Run all verification gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
git diff --check
```

With PostgreSQL running:

```bash
uv run alembic upgrade head
CRAWLING_MCP_RUN_STORAGE_INTEGRATION=1 uv run pytest -m integration tests/integration/test_postgres_monitoring.py -q
```

- [ ] **Step 3: Review the final diff against the design**

Confirm every design test requirement has direct automated evidence and no public MCP schema changed.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/PROGRESS.md
git commit -m "docs: describe reliable continuous monitoring"
```
