# PostgreSQL and MinIO Article Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every crawl execution and its extracted article records in PostgreSQL, while keeping raw HTML and failure diagnostics in MinIO.

**Architecture:** Keep the application service and MCP response models independent of storage. Add article metadata to the extracted page model, pass the source snapshot to the repository, and implement a PostgreSQL repository backed by a small MinIO object-store adapter. PostgreSQL owns queryable metadata and references immutable MinIO objects by job-scoped keys.

**Tech Stack:** Python 3.12, SQLAlchemy async + asyncpg, Alembic, MinIO Python SDK, PostgreSQL 16, MinIO, Docker Compose.

## Global Constraints

- Preserve all existing MCP tool inputs and response shapes; the new article metadata fields are additive.
- Store one article row per extraction per crawl job; never upsert by URL.
- Store article `published_at` and `source` as nullable when metadata is unavailable.
- Store every successful raw HTML page and all failure diagnostics in MinIO.
- Do not expose database query MCP tools in this change.

---

### Task 1: Article extraction model and metadata

**Files:**
- Modify: `src/crawling_mcp/domain/models.py`
- Modify: `src/crawling_mcp/adapters/extractors/generic.py`
- Modify: `tests/unit/test_extractors.py`

**Interfaces:**
- `PageItem.published_at: datetime | None`
- `PageItem.source: str | None`

- [ ] Write tests for JSON-LD, Open Graph and `<time>` metadata precedence and missing values.
- [ ] Run the focused extractor tests and observe failures for absent fields.
- [ ] Add additive page fields and deterministic metadata extraction with timezone-aware dates.
- [ ] Run focused extractor tests and the unit suite.

### Task 2: Object-store and repository contracts

**Files:**
- Create: `src/crawling_mcp/ports/object_store.py`
- Create: `src/crawling_mcp/adapters/storage/minio_store.py`
- Modify: `src/crawling_mcp/ports/repository.py`
- Modify: `src/crawling_mcp/application/crawl_service.py`
- Modify: `tests/unit/test_repositories.py`

**Interfaces:**
- `ObjectStore.put_html(job_id, url, html) -> StoredObject`
- `ObjectStore.put_artifact(job_id, name, content, content_type) -> StoredObject`
- `CrawlRepository.save_page(job_id, item, snapshot) -> None`

- [ ] Write failing object-key and repository-call contract tests.
- [ ] Add immutable job-scoped object keys, SHA-256 metadata and source-snapshot forwarding.
- [ ] Update memory/file repositories to accept the expanded contract without altering their persistence semantics.
- [ ] Run focused repository and crawl-service tests.

### Task 3: PostgreSQL schema and repository

**Files:**
- Create: `src/crawling_mcp/adapters/storage/postgres_repository.py`
- Create: `alembic.ini`, `alembic/env.py`, `alembic/versions/<revision>_create_crawl_storage.py`
- Modify: `tests/integration/test_postgres_repository.py`

**Interfaces:**
- `crawl_jobs`, `articles`, and `crawl_failures` tables.
- `PostgresRepository` implements `CrawlRepository` and persists article object references.

- [ ] Write integration tests for append-only URLs, nullable metadata, job completion and MinIO references.
- [ ] Implement the migration and repository transaction flow: upload before article insertion; best-effort object deletion when database insertion fails.
- [ ] Run migration against PostgreSQL and focused integration tests.

### Task 4: MinIO failure artifacts and application wiring

**Files:**
- Modify: `src/crawling_mcp/infrastructure/artifacts.py`
- Modify: `src/crawling_mcp/bootstrap.py`
- Modify: `src/crawling_mcp/infrastructure/config.py`
- Modify: `pyproject.toml`, `.env.example`
- Modify: `tests/unit/test_artifacts.py`, `tests/unit/test_server.py`

**Interfaces:**
- `repository` accepts `memory`, `file`, or `postgres`.
- PostgreSQL DSN and MinIO endpoint/bucket/credentials are runtime configuration.

- [ ] Write failing settings and artifact-writer tests.
- [ ] Add production composition wiring and MinIO-backed artifact writer that returns object references in existing failure payloads.
- [ ] Run unit tests for configuration, artifacts and container bootstrap.

### Task 5: Compose, documentation and end-to-end verification

**Files:**
- Modify: `docker-compose.yml`, `docker-compose.test.yml`, `Dockerfile`, `README.md`
- Modify: `tests/integration/conftest.py`, `tests/integration/test_public_crawl.py`

- [ ] Write a failing Compose-backed integration test that asserts article columns and raw HTML object existence.
- [ ] Add PostgreSQL, MinIO and one-shot migration services with health checks; make MCP startup wait for migration completion.
- [ ] Document external-service configuration and direct article-table query contract.
- [ ] Run ruff, mypy, unit tests, integration tests, Compose config/build and an MCP stdio smoke test.
