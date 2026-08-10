# Continuous Article Monitoring Implementation Plan

**Goal:** Run periodic crawling in a Python Worker, extract site-aware article
candidates, and keep only the latest article in the existing `ARTICLE` table while
storing scheduling, state, and run metadata separately.

**Architecture:** Preserve Ports & Adapters. Worker and MCP remain thin adapters;
`MonitoringService` calls the existing `CrawlService`; `ArticleExtractor` converts
raw page observations to `ArticleCandidate`; `ArticlePersistenceService` owns
NEW/UPDATED/UNCHANGED decisions through focused repository ports.

## 1. Reconcile the generic crawl boundary

- Remove article-only fields from `PageItem`.
- Add an internal `persist_result` execution switch.
- Preserve page observation and conditional HTTP hooks.
- Test that Worker crawls do not persist generic result bodies while manual crawls
  retain existing repository behavior.

## 2. Add article domain and extraction

- Add `ArticleCandidate`, `Article`, `ArticleCrawlState`, `ArticleChangeSummary`,
  `CrawlRun`, and compact result DTOs.
- Add deterministic URL/text/time canonicalization and article fingerprints.
- Add `ArticleExtractor`/resolver ports, registry, and a structured-data adapter.
- Test JSON-LD, OpenGraph, semantic HTML, canonical URL, reporter, publisher, and
  publication time with HTML fixtures.

## 3. Replace snapshot ports with article persistence ports

- Keep `TargetRepository` and lease operations.
- Add focused `ArticleRepository`, `ArticleCrawlStateRepository`, and
  `CrawlRunRepository` protocols plus a monitoring UoW.
- Implement concurrency-safe in-memory adapters for deterministic tests.
- Test target CRUD/claims, article CRUD, state upsert/touch, and run queries.

## 4. Implement ArticlePersistenceService

- Write tests for missing ARTICLE -> NEW, same fingerprint -> UNCHANGED, changed
  fingerprint -> UPDATED, and baseline state for pre-existing ARTICLE rows.
- Ensure inserts omit IDs, unchanged content never updates ARTICLE, and state keeps
  the last meaningful change.
- Add structured `article_created` and `article_updated` logs.

## 5. Rework MonitoringService

- Create the DB-owned `CRAWL_RUN` before crawling.
- Load validators from article crawl state.
- Run `CrawlService` with generic result persistence disabled.
- Extract candidates per observed page and persist them through
  `ArticlePersistenceService`.
- Aggregate visited/new/updated/unchanged/failed counts and update run/target state.
- Preserve due-only execution, leases, failure isolation, backoff, and timeouts.

## 6. Implement non-destructive PostgreSQL storage

- Define SQLAlchemy Core mappings for the existing exact `ARTICLE` columns and only
  the three new tables.
- Rewrite the initial Alembic migration to require/validate ARTICLE, never create or
  drop it, check duplicate URLs before adding a unique index, and create/drop only
  crawler-owned objects.
- Implement async repositories with IDs omitted and `RETURNING` used for DB-owned
  UUIDv7 values.
- Run migration and repository integration tests against PostgreSQL 18.

## 7. Rework compact MCP queries

- Keep target configuration/list/manual-run/status commands high level.
- Replace snapshot change/detail tools with `get_recent_article_changes` and
  `get_article`.
- Prove summaries exclude `ar_content` and full content appears only in explicit
  article lookup.

## 8. Wire runtime and documentation

- Register article extractors and services in `bootstrap.py`.
- Keep one BrowserManager per MCP/Worker process.
- Keep external `DATABASE_URL`/PostgreSQL environment configuration with no MinIO.
- Keep Compose process separation; document external-PostgreSQL deployment as well
  as the optional local PostgreSQL service.
- Update README with architecture, schema, execution, Hermes flow, duplicate-body
  prevention, and Kafka extension seams.

## 9. Verification and publication

- Focused TDD loops for each behavior.
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src`
- unit and full pytest
- PostgreSQL migration upgrade/downgrade/upgrade and integration suite
- Docker Compose config/startup smoke checks
- diff/security/self-review, intentional commits, and push
