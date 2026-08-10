# Continuous Monitoring Architecture Design

## Goal

Move periodic crawling out of Hermes and into a long-running Python worker while
preserving the existing hexagonal architecture. Hermes and MCP remain on-demand
interfaces for target management, status, change summaries, and detail retrieval.

## Existing architecture

The current dependency direction is retained:

```text
FastMCP adapter -> CrawlService/AuthService -> Protocol ports -> adapters
```

`CrawlService` owns validation, authentication, engine selection, extraction, and
job persistence. `AdaptiveCrawlerEngine` tries HTTP before the shared Playwright
browser. `ApplicationContainer` owns the egress proxy and browser lifecycle. MCP
tools contain transport validation and serialization only.

## Target architecture

```text
Hermes -> MCP query/command tools -> monitoring application services -> PostgreSQL

Worker adapter -> MonitoringService -> CrawlService -> AdaptiveCrawlerEngine
                                      -> HTTP / shared Playwright browser
                                      -> Website
MonitoringService -> ChangeDetector -> monitoring unit of work -> PostgreSQL
```

The worker never calls MCP. MCP never calls Crawlee, Playwright, or a repository
directly.

## Domain model

### CrawlTarget

Stores the monitoring contract and scheduler state:

- database-generated UUIDv7 identifier
- URL, interval, enabled state, crawl mode, optional auth profile
- bounded crawl options: max pages/depth, timeouts, retries, concurrency, robots,
  delay, URL patterns, domain and tracking policies
- last/next crawl timestamps
- failure count, last error/failed timestamp, next retry timestamp
- lease owner and lease expiry for duplicate-run prevention
- created/updated timestamps

### CrawlSnapshot

A snapshot is a changed content version for one target/page URL. It references an
article row that owns the extracted body and stores content hash, ETag,
Last-Modified, stable metadata, depth, collected time, and last-seen time.
Unchanged checks update `last_seen_at` and do not duplicate the body.

### CrawlChange

Stores only meaningful `NEW` and `UPDATED` events and references the previous and
current snapshots. `UNCHANGED` remains a detector outcome and job counter rather
than an append-only event. `DELETED` is intentionally deferred because a bounded
or partially failed crawl cannot distinguish deletion from an unvisited page.

### ChangeDetector

Canonicalizes extracted `PageItem` values before SHA-256 hashing:

- normalize the effective canonical URL and remove tracking parameters
- Unicode NFKC-normalize title and content
- collapse whitespace
- include stable title/content identity
- exclude collection time, response status, and arbitrary volatile metadata

Outcomes are `NEW`, `UPDATED`, and `UNCHANGED`.

## Application services

### MonitoringService

`run_target` loads current snapshots, supplies HTTP validators to `CrawlService`,
observes extracted pages without changing the public MCP crawl response, detects
changes, atomically stores snapshots/events, and updates target/job state.

`run_due_targets` claims due targets through the target repository and isolates
per-target failures so one timeout cannot terminate the worker loop.

### MonitoringQueryService

Provides bounded target, status, recent-change, and change-detail DTOs to MCP.
Summary methods never include article content. Only detail lookup includes content.

## Ports and persistence

Keep `CrawlRepository` for crawl-job persistence and add focused protocols:

- `TargetRepository`
- `SnapshotRepository`
- `ChangeRepository`
- `MonitoringUnitOfWork`

PostgreSQL implementations are separate classes sharing a SQLAlchemy async session
and unit of work. In-memory implementations support deterministic unit tests.

PostgreSQL uses SQLAlchemy Async, asyncpg, and Alembic. PostgreSQL INSERT statements
for article, target, snapshot, and change IDs omit the ID and use
`DEFAULT uuidv7()` with `RETURNING id`. No MinIO dependency is introduced.

## Database schema

- `article`: collected/published time, title, content, source, URL, content hash;
  unique URL/hash content versions
- `crawl_jobs`: target link, state, counts, timing, and safe failure summary
- `crawl_job_pages`: small association between jobs and article versions
- `crawl_targets`: configuration, schedule, retry, and lease state
- `crawl_snapshots`: target/page version, validators, metadata, last-seen state
- `crawl_changes`: NEW/UPDATED event and previous/current snapshot references

Existing FileRepository remains supported. PostgreSQL is the operational default in
Docker Compose; migration runs before the MCP server and worker.

## Conditional HTTP design

Previous ETag and Last-Modified values are passed through an internal crawl context,
not public MCP request fields. The HTTP adapter applies `If-None-Match` and
`If-Modified-Since` per known URL. A 304 observation bypasses parsing, extraction,
hashing, and browser fallback. Known prior page URLs are seeded for multi-page
targets so a 304 start page does not prevent child validation. Browser-only and
authenticated browser requests do not use this optimization.

## Worker and leases

The scheduler polls at a configured interval and atomically claims batches with
`FOR UPDATE SKIP LOCKED` plus a time-bound lease. The runner applies a per-target
timeout, exponential retry backoff with a cap, structured logging, and graceful
SIGINT/SIGTERM shutdown. A stale lease can be reclaimed after worker failure.

## MCP surface

Existing tools remain compatible:

- `scrape_page`
- `crawl_site`
- `validate_session`
- `list_supported_sites`

Monitoring tools:

- `list_crawl_targets`
- `configure_crawl_target`
- `run_crawl_target`
- `get_crawl_status`
- `get_recent_changes`
- `get_change_detail`

The first five monitoring responses are compact DTOs. Full content is returned only
by `get_change_detail`.

## Observability and failure behavior

Structured events include `crawl_target_started`, `crawl_target_completed`,
`crawl_target_failed`, and `change_detected`, with target/job/url/mode/duration and
page counters. Secrets and raw exceptions are not exposed through MCP.

## Verification

Tests cover detector outcomes, repository CRUD, due/disabled target behavior,
failure isolation, monitoring orchestration, compact MCP responses, conditional
requests and 304 behavior, PostgreSQL migrations/repositories, worker shutdown,
Compose structure, and all existing behavior. Final gates are ruff check/format,
strict mypy, unit tests, PostgreSQL integration tests, and the full pytest suite.
