# Continuous Monitoring Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each behavior and superpowers:verification-before-completion before claiming success.

**Goal:** Add a PostgreSQL-backed continuous crawling worker that calls `MonitoringService` and the existing `CrawlService` directly, stores only changed content versions, and exposes compact monitoring tools through MCP.

**Architecture:** Preserve the existing hexagonal dependency direction. Add pure monitoring domain types and change detection, focused monitoring repository ports plus a unit of work, PostgreSQL and in-memory adapters, a scheduler/runner adapter, and thin MCP query/command tools. Extend the internal crawl execution context for page observations and conditional HTTP without changing existing public crawl requests.

**Tech Stack:** Python 3.12, Pydantic 2, asyncio, Crawlee 1.9, Playwright 1.62, SQLAlchemy 2 async, asyncpg, Alembic, PostgreSQL 18, FastMCP, structlog, pytest, ruff, mypy.

---

## Task 1: Add PostgreSQL and migration dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/crawling_mcp/infrastructure/config.py`
- Modify: `.env.example`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_packaging.py`

1. Write failing tests for PostgreSQL repository settings, worker poll/lease/backoff settings, and required package data.
2. Run the focused tests and confirm the expected failures.
3. Add SQLAlchemy, asyncpg, and Alembic dependencies plus bounded settings.
4. Refresh `uv.lock` and run the focused tests.
5. Commit `build: add postgres worker dependencies`.

## Task 2: Add monitoring domain types and pure change detection

**Files:**
- Create: `src/crawling_mcp/domain/monitoring.py`
- Create: `src/crawling_mcp/domain/change_detector.py`
- Modify: `src/crawling_mcp/domain/enums.py`
- Modify: `src/crawling_mcp/domain/models.py`
- Test: `tests/unit/test_change_detector.py`
- Test: `tests/unit/test_monitoring_models.py`

1. Write tests for NEW, UPDATED, UNCHANGED, Unicode/whitespace canonicalization, tracking URL normalization, target due rules, and retry schedule.
2. Run them and verify missing symbols fail.
3. Implement compact immutable domain models and the pure detector.
4. Run focused tests, ruff, and mypy for these files.
5. Commit `feat(domain): model crawl monitoring changes`.

## Task 3: Add focused repository ports and in-memory adapters

**Files:**
- Create: `src/crawling_mcp/ports/monitoring.py`
- Create: `src/crawling_mcp/adapters/storage/monitoring_memory.py`
- Test: `tests/unit/test_monitoring_repositories.py`

1. Write contract tests for target CRUD, due claims, disabled filtering, lease reclaim, latest snapshots, last-seen updates, change ordering, and detail retrieval.
2. Confirm contract tests fail before the adapters exist.
3. Implement `TargetRepository`, `SnapshotRepository`, `ChangeRepository`, `MonitoringUnitOfWork`, and the concurrency-safe in-memory implementation.
4. Run repository tests and strict typing.
5. Commit `feat(storage): add monitoring repository ports`.

## Task 4: Add internal crawl observations and HTTP validators

**Files:**
- Modify: `src/crawling_mcp/domain/models.py`
- Modify: `src/crawling_mcp/application/crawl_service.py`
- Modify: `src/crawling_mcp/adapters/crawlee/http_engine.py`
- Modify: `src/crawling_mcp/adapters/crawlee/browser_engine.py`
- Modify: `src/crawling_mcp/adapters/crawlee/adaptive_engine.py`
- Test: `tests/unit/test_crawl_service.py`
- Test: `tests/unit/test_http_cache.py`
- Test: `tests/unit/test_adaptive_engine.py`

1. Write failing tests that a page observer receives snapshot/items, ETag and Last-Modified are captured, requests send conditional headers, known pages are seeded, and 304 skips extractor/browser fallback.
2. Add excluded internal callback/cache fields to `CrawlContext` and an optional execution object to `CrawlService` while preserving existing call signatures.
3. Populate response headers in both engines and implement HTTP 304 observations.
4. Seed cached page requests with depth and validators; ensure AdaptiveCrawlerEngine treats 304 as final HTTP success.
5. Run all crawl/engine tests and commit `feat(crawl): support monitoring observations and http validators`.

## Task 5: Add PostgreSQL schema and Alembic migration

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/20260810_01_continuous_monitoring.py`
- Create: `src/crawling_mcp/adapters/storage/postgres/schema.py`
- Test: `tests/unit/test_migrations.py`

1. Write tests that inspect migration/schema text for all required tables, foreign keys, indexes, lease columns, UUIDv7 defaults, and no MinIO dependency.
2. Confirm tests fail.
3. Define SQLAlchemy Core metadata and Alembic upgrade/downgrade.
4. Ensure article/target/snapshot/change INSERT identities are DB-generated.
5. Run migration unit tests and commit `feat(storage): add continuous monitoring schema`.

## Task 6: Implement PostgreSQL repositories

**Files:**
- Create: `src/crawling_mcp/adapters/storage/postgres/__init__.py`
- Create: `src/crawling_mcp/adapters/storage/postgres/crawl_repository.py`
- Create: `src/crawling_mcp/adapters/storage/postgres/target_repository.py`
- Create: `src/crawling_mcp/adapters/storage/postgres/snapshot_repository.py`
- Create: `src/crawling_mcp/adapters/storage/postgres/change_repository.py`
- Create: `src/crawling_mcp/adapters/storage/postgres/unit_of_work.py`
- Test: `tests/unit/test_postgres_repositories.py`
- Test: `tests/integration/test_postgres_monitoring.py`

1. Write SQL-level unit tests proving IDs are omitted, due claims use `FOR UPDATE SKIP LOCKED`, and repository responsibilities stay separated.
2. Implement async SQLAlchemy repositories with a shared session factory and transactional unit of work.
3. Add PostgreSQL integration contract tests for target CRUD/claim, content deduplication, snapshots, change detail, and rollback.
4. Run unit tests; start PostgreSQL, migrate, and run integration tests.
5. Commit `feat(storage): implement postgres monitoring repositories`.

## Task 7: Implement MonitoringService

**Files:**
- Create: `src/crawling_mcp/application/monitoring_service.py`
- Test: `tests/unit/test_monitoring_service.py`

1. Write orchestration tests for first collection, unchanged collection, updated content, multi-page counts, 304 handling, disabled/not-due behavior, success scheduling, timeout/failure backoff, and failure isolation.
2. Confirm failures before implementation.
3. Implement `run_target` and `run_due_targets` using the CrawlRunner and monitoring unit-of-work ports.
4. Add structured start/completion/failure/change logs and safe error storage.
5. Run focused tests and commit `feat(application): add monitoring service`.

## Task 8: Implement compact monitoring query/command services and MCP tools

**Files:**
- Create: `src/crawling_mcp/application/monitoring_query_service.py`
- Modify: `src/crawling_mcp/adapters/mcp/tools.py`
- Modify: `src/crawling_mcp/server.py`
- Test: `tests/unit/test_monitoring_queries.py`
- Test: `tests/unit/test_mcp_monitoring_tools.py`

1. Write tests for target configuration/listing, status, manual run, bounded recent changes, and explicit detail lookup.
2. Assert summary responses contain no `content` or raw metadata and enforce result limits.
3. Implement application DTOs/services and six thin MCP tools.
4. Extend transport validation without repository or crawler imports in the MCP adapter.
5. Run MCP/query tests and commit `feat(mcp): expose compact monitoring tools`.

## Task 9: Add worker scheduler, runner, and entrypoint

**Files:**
- Create: `src/crawling_mcp/adapters/worker/__init__.py`
- Create: `src/crawling_mcp/adapters/worker/scheduler.py`
- Create: `src/crawling_mcp/adapters/worker/runner.py`
- Create: `src/crawling_mcp/worker.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_worker.py`

1. Write tests for due-only execution, disabled skipping, per-target failure isolation, stop-event polling, no MCP dependency, and graceful cancellation.
2. Implement a clock-injectable scheduler and signal-aware runner.
3. Expose `python -m crawling_mcp.worker` and `crawling-mcp-worker`.
4. Run worker and packaging tests.
5. Commit `feat(worker): run continuous crawl scheduler`.

## Task 10: Wire process-specific containers and Docker Compose

**Files:**
- Modify: `src/crawling_mcp/bootstrap.py`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.test.yml`
- Modify: `Dockerfile`
- Test: `tests/unit/test_bootstrap_monitoring.py`
- Test: `tests/unit/test_compose.py`

1. Write tests for memory/file compatibility, PostgreSQL MCP composition, Worker -> MonitoringService -> CrawlService wiring, one BrowserManager per process, migration ordering, and no MinIO service.
2. Add shared component construction plus MCP/worker containers with correct lifecycle and repository ownership.
3. Add PostgreSQL, migrate, MCP server, and crawler-worker services.
4. Run bootstrap/Compose tests and Docker config validation.
5. Commit `feat(runtime): wire postgres mcp and crawler worker`.

## Task 11: Document operations and Hermes usage

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

1. Document architecture, migrations, local/Compose commands, target configuration, worker lifecycle, schema, MCP tools, compact responses, Hermes call patterns, cost reduction, and future Kafka/distributed-worker seams.
2. Validate documented commands and environment names against code.
3. Run README/package smoke checks.
4. Commit `docs: document continuous crawler operations`.

## Task 12: Full verification and publication

1. Run `uv run ruff check .`.
2. Run `uv run ruff format --check .`.
3. Run `uv run mypy src`.
4. Run `uv run pytest`.
5. Run PostgreSQL migration and repository integration tests.
6. Run `docker compose config` and a worker/MCP startup smoke test.
7. Inspect `git diff --check`, status, migration downgrade/upgrade, and ensure no secrets or user files were included.
8. Use `superpowers:requesting-code-review`, address concrete findings, rerun all verification, then use `superpowers:finishing-a-development-branch`.
9. Push `feat/continuous-monitoring` to GitHub and report commit, verification evidence, final architecture, Hermes usage, LLM savings, and Kafka/distributed-worker extension points.
