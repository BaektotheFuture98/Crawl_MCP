# Monitoring Reliability Refactor Design

## Context

The continuous monitoring branch already follows ports-and-adapters architecture, but four
implementation boundaries are unsafe for production workloads:

1. A target lease can expire while its crawl is still running, allowing duplicate execution.
2. One `ARTICLE_CRAWL_STATE` row is shared by all targets and changes ownership when another
   target observes the same canonical article URL.
3. Monitoring retains deep copies of every HTML snapshot until the crawl completes while the
   crawler also retains every extracted `PageItem`.
4. Article creation uses a read-then-insert sequence and fails under concurrent discovery of the
   same canonical URL.

The existing hexagonal structure remains the architectural baseline. This refactor changes the
reliability contracts inside the existing ports, services, adapters, and migrations.

## Goals

- Guarantee that only the current lease owner can renew or finalize a target execution.
- Keep a long-running crawl leased until it completes or the worker stops.
- Avoid claiming work that will sit idle behind earlier targets in a batch.
- Store article content globally by canonical URL while storing validators and observation state
  independently for every target.
- Make article creation idempotent under concurrent workers.
- Process monitoring pages incrementally with memory bounded by crawler concurrency rather than
  total pages.
- Preserve the existing MCP tool surface and compact monitoring responses.

## Non-goals

- Replacing PostgreSQL polling with Kafka or another queue.
- Adding article history or raw snapshot tables.
- Changing public `scrape_page` and `crawl_site` response schemas.
- Making a whole multi-page crawl one database transaction.

## Chosen approach

### Lease fencing and heartbeat

`TargetRepository` gains owner-aware operations:

- `renew_lease(target_id, lease_owner, now, lease_seconds) -> bool`
- `mark_succeeded(..., lease_owner) -> bool`
- `mark_failed(..., lease_owner) -> bool`

All updates include both `target_id` and `lease_owner` in their predicate. A stale worker cannot
clear or overwrite a lease acquired by a newer worker. `MonitoringService` starts a heartbeat for
every claimed target and renews at one third of the configured lease duration. Losing the lease
causes the current run to stop finalizing target state and raises a domain-level lost-lease error.

Scheduled work is claimed one target at a time immediately before execution, repeated up to the
configured batch size. This preserves bounded batches without pre-leasing targets that are still
waiting behind earlier work.

Before a new run is created for a target, any older `RUNNING` run for the same target whose lease
has expired is marked `FAILED` with `error="lease_expired"` and a completion timestamp. This keeps
status queries truthful after worker crashes.

### Target-scoped observation state

`ARTICLE` remains unique by canonical URL and contains the latest article fields. The
`ARTICLE_CRAWL_STATE` identity becomes `(target_id, article_id)`, with a unique constraint on
`(target_id, url)`. Two overlapping targets may therefore observe the same article without moving
ETag, last-seen, or change metadata between targets.

State repository methods become target-scoped:

- `find_by_url(target_id, url)`
- `create` and `save` operate on `(target_id, article_id)`
- `list_by_target` and `recent_changes` retain their current behavior

`NEW`, `UPDATED`, and `UNCHANGED` are evaluated per target observation. If target B sees an article
already stored globally by target A, the article row is reused but target B records its first
observation as `NEW`.

A new Alembic revision migrates the deployed schema without editing the existing migration. It
replaces the single-column state primary key and unique URL constraint while preserving rows.

### Atomic article creation

`ArticleRepository` replaces `insert` with `insert_or_get`. PostgreSQL uses
`INSERT ... ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING ...`, so concurrent first
observations return one database-owned article identity. The in-memory adapter implements the same
contract.

After obtaining the global article row, `ArticlePersistenceService` compares the target-scoped
state with the new candidate. An updated candidate updates the shared latest article row; first
observation creates only the missing target-scoped state.

### Streaming monitoring pipeline

`CrawlExecution` gains `collect_items: bool = True`. Crawler engines still invoke page callbacks,
but append extracted items to `CrawlResult.items` only when `collect_items` is true. Public manual
crawls keep the existing default.

Monitoring uses `collect_items=False`. Its page callback extracts article candidates and persists
them before returning. It does not retain `PageSnapshot` instances. A lock protects per-run
canonical URL reservation and counters; a failed persistence removes the reservation before the
error propagates so a crawler retry can try again. Not-modified callbacks update only the matching
target-scoped state immediately.

Extractor failures increment `failed_pages` and remain isolated to their page. Persistence failures
propagate through the crawler's existing page failure/retry behavior. The final run stores crawler
failures plus isolated extraction failures.

## Error handling

- A lost heartbeat sets a shared event and prevents stale finalization.
- Owner-guarded completion returning false is treated as lost lease.
- PostgreSQL unique conflicts for article URLs are handled by the upsert itself.
- State uniqueness is target-scoped; an unexpected conflict rolls back the page transaction.
- Worker process crashes are recovered when the target is next claimed.

## Testing

Tests must prove:

1. An active run renews its lease and cannot be reclaimed after the original expiry.
2. A stale owner cannot mark a target successful or failed.
3. Scheduled batches claim the next target only after the previous execution finishes.
4. A stale `RUNNING` run is reconciled before a new run starts.
5. Two targets observing one canonical article retain two independent states.
6. Concurrent article discovery returns one global article row without failing either observation.
7. Monitoring does not retain snapshots or result items and processes each page incrementally.
8. Manual crawl behavior and MCP schemas remain unchanged.

Unit tests cover in-memory contracts and service orchestration. PostgreSQL integration tests cover
the migration, owner-fenced updates, composite state identity, and concurrent upsert.

## Alternatives considered

### Increase the fixed lease duration

Rejected because job duration and batch wait time are variable. No fixed value prevents stale
workers from finalizing after a later worker acquires the target.

### Prohibit overlapping targets

Rejected because list pages and category pages naturally overlap. Enforcing disjoint URL sets is
not practical and would make monitoring configuration brittle.

### Buffer a smaller number of snapshots

Rejected in favor of direct incremental processing. A bounded buffer reduces peak memory but adds
queue lifecycle and error propagation complexity without improving the current single-service
boundary.
