# Continuous Article Monitoring Architecture Design

## Goal

Move periodic crawling out of Hermes and into a long-running Python worker while
preserving the existing hexagonal architecture. `ARTICLE` remains the sole final
article store. Crawler state and run metadata live in separate PostgreSQL tables.

## Architecture

```text
Hermes -> MCP adapter -> MonitoringQueryService -> repository ports -> PostgreSQL

Worker adapter -> MonitoringService -> CrawlService -> AdaptiveCrawlerEngine
                                      -> HTTP / shared Playwright browser
               -> ArticleExtractor -> ArticleCandidate
               -> ArticlePersistenceService -> repository ports -> PostgreSQL
```

MCP and Worker adapters never call Crawlee, Playwright, or SQL directly. The Worker
calls application services directly and never calls MCP. `CrawlService` stays
reusable by MCP, CLI, and Worker. HTTP-first fallback and the process-scoped
`BrowserManager` lifecycle remain unchanged.

## Article boundary

`PageItem` stays engine-neutral and generic. Article-specific fields are not added
to it. Monitoring observes the raw `PageSnapshot` through the internal
`CrawlExecution` hook and passes it to a separately registered `ArticleExtractor`.

`ArticleCandidate` contains the canonical article URL, title, body, reporter,
publisher, and publication time. The default structured-data adapter uses this
priority order:

1. schema.org `Article`/`NewsArticle` JSON-LD
2. OpenGraph/article metadata
3. semantic `<article>`, heading, author, and `<time>` elements

Site-specific CSS selectors belong in article extractor adapters, never in
`GenericExtractor`, the domain, or application services. Pages without a credible
title and body produce no candidate.

## Change detection and persistence

`ArticleChangeDetector` canonicalizes the candidate before SHA-256 hashing:

- normalized canonical URL with fragments and tracking parameters removed
- Unicode NFKC normalization and collapsed whitespace
- title, body, reporter, publisher, and normalized publication timestamp

`ArticlePersistenceService` loads the current article and crawl state by canonical
URL and performs one atomic outcome:

- `NEW`: `ARTICLE` does not exist; insert it and create state.
- `UPDATED`: fingerprint differs; update `ARTICLE` and meaningful-change state.
- `UNCHANGED`: do not update `ARTICLE`; only touch state last-seen and validators.

If an article predates monitoring state, its current row is fingerprinted first.
Matching content creates baseline state without reporting a new change; different
content is `UPDATED`. `UNCHANGED` never overwrites the last meaningful change type
or timestamp.

## Existing ARTICLE contract

The migration requires and validates this existing table, and never creates,
drops, or recreates it:

```sql
CREATE TABLE ARTICLE (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    ar_title TEXT,
    ar_content TEXT,
    reporter VARCHAR(100),
    publisher VARCHAR(100),
    url TEXT,
    published_at TIMESTAMP
);
```

The migration adds a unique URL index only after checking for duplicate non-null
URLs. It fails with an actionable error instead of deleting ambiguous existing
rows. All application inserts omit `id`; PostgreSQL `uuidv7()` owns identity.

## Added tables

- `CRAWL_TARGET`: schedule, bounded crawl configuration, retry state, and lease.
- `ARTICLE_CRAWL_STATE`: article/target relation, canonical URL, content hash,
  ETag, Last-Modified, first/last seen, and last meaningful change.
- `CRAWL_RUN`: one Worker execution with status, timing, and compact counters.

There are no snapshot, article-history, raw-article, change-event, job-page, or
object-storage tables. Recent changes are queried from the latest meaningful
change fields in `ARTICLE_CRAWL_STATE` joined to `ARTICLE`.

## Crawl result persistence

The existing `FileRepository` remains the default for manual MCP/CLI crawls.
Worker executions set `CrawlExecution.persist_result=False`, so the same article
body is not written to `data/results`. PostgreSQL runtime uses an in-memory generic
crawl repository for manual transport compatibility; final monitored articles are
written only through `ArticlePersistenceService`.

Failure diagnostic artifacts remain allowed and contain operational diagnostics,
not a second permanent article corpus.

## Conditional HTTP

ETag and Last-Modified values are stored in `ARTICLE_CRAWL_STATE` and passed into
the internal crawl context. The HTTP adapter emits `If-None-Match` and
`If-Modified-Since`. A 304 response bypasses parsing, article extraction, hashing,
and browser fallback, and only touches state last-seen/validators.

## Scheduling and failure behavior

The single-process asyncio scheduler claims due targets with PostgreSQL
`FOR UPDATE SKIP LOCKED` and a time-bound lease. An expired lease is reclaimable
after a crash. A target failure records exponential backoff and a failed
`CRAWL_RUN`; it does not stop later targets. SIGINT/SIGTERM trigger graceful
shutdown. Manual runs use the same lease boundary and cannot overlap scheduled
runs.

## MCP surface

Existing tools remain:

- `scrape_page`
- `crawl_site`
- `validate_session`
- `list_supported_sites`

High-level monitoring tools are:

- `list_crawl_targets`
- `configure_crawl_target`
- `run_crawl_target`
- `get_crawl_status`
- `get_recent_article_changes`
- `get_article`

Change summaries contain article ID, type, title, publisher, URL, publication time,
and last-changed time, never `ar_content`. Only `get_article(article_id)` returns
the selected body.

## Extension boundary

Kafka or multiple Workers replace the scheduler/claim adapter and may add an
outbox/queue visibility mechanism. `MonitoringService`, `CrawlService`, article
extractors, article persistence policy, crawler engines, and MCP query contracts
remain stable.
