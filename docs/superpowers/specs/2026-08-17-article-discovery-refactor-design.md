# Article Discovery Architecture Refactor Design

## Context

The repository currently implements continuous article **change detection**. It stores a
target-scoped `ArticleCrawlState`, fingerprints article content, exposes
`get_recent_article_changes`, and reports new/updated/unchanged counters.

The approved product contract is different: after a target is registered, collect newly
published articles incrementally by publication time. Article edits are not a product concern.
The architecture must also make the existing hexagonal boundaries explicit instead of mixing
ports, inbound adapters, outbound adapters, and composition code.

## Goals

- Collect only articles whose `published_at` belongs to a bounded discovery window.
- Advance a target watermark only after a successful, owner-fenced crawl run.
- Preserve a small overlap and safety lag so late publication and clock skew do not lose data.
- Keep one globally unique `ARTICLE` row per normalized canonical URL.
- Record which target discovered which article in `ARTICLE_DISCOVERY`.
- Preserve lease heartbeat, stale-owner fencing, stale-run recovery, crawl bounds, SSRF policy,
  authentication, and generic MCP crawl tools.
- Replace change-oriented MCP queries and counters with discovery-oriented contracts.
- Restructure the source tree into Domain, Application, Adapters, and Bootstrap boundaries.
- Document setup, migration, target registration, worker execution, manual execution, and query
  usage in `README.md`.

## Non-goals

- Detecting or storing later article edits.
- Keeping content hashes or change history.
- Adding snapshot, object-storage, event-bus, or outbox infrastructure.
- Rewriting every Pydantic model as a dataclass. Domain/DTO separation is required; a wholesale
  validation-library conversion is not.
- Removing the generic `scrape_page` and `crawl_site` MCP tools.

## Product Semantics

### Discovery window

Each target stores:

- `discovery_watermark_at`: end of the last successfully completed discovery window.
- `discovery_lag_seconds`: safety lag subtracted from the current time.
- `discovery_overlap_seconds`: overlap subtracted from the previous watermark.

For a run at `now`:

```text
base  = discovery_watermark_at or created_at
start = base - discovery_overlap_seconds
end   = now - discovery_lag_seconds
```

The window is inclusive at `start` and exclusive at `end`: `start <= published_at < end`.
If `end <= start`, the crawl succeeds with an empty window and advances only when doing so would
move the watermark forward.

On success, the watermark advances to `end`, even when no article is found. This avoids rescanning
an empty period forever. The overlap makes the advance safe for late-visible articles, while
global URL uniqueness and discovery idempotency absorb repeats.

Candidates without a trustworthy `published_at` are skipped by the collection use case. The run
records them as neither inserted nor duplicate because they are outside the product's identity
rule.

### Article and discovery identity

- `ARTICLE.url` remains globally unique after URL normalization.
- `ARTICLE_DISCOVERY` has primary key `(target_id, article_id)`.
- `discovered_at` is the time this system first recorded that target/article relationship.
- Re-observing an article inside an overlap window does not update article content and does not
  create another discovery row.

### Run counters

`CRAWL_RUN` and collection results expose:

- `visited_pages`
- `discovered_articles`: unique in-window article candidates observed during this run
- `inserted_articles`: candidates that created a new global `ARTICLE`
- `duplicate_articles`: in-window candidates whose global `ARTICLE` already existed
- `failed_pages`

The invariant is `discovered_articles == inserted_articles + duplicate_articles`.

## Data Model and Migration

Create Alembic revision `20260817_03` after `20260817_02`.

### `crawl_target`

Add:

- `discovery_watermark_at TIMESTAMPTZ NULL`
- `discovery_lag_seconds INTEGER NOT NULL DEFAULT 30`
- `discovery_overlap_seconds INTEGER NOT NULL DEFAULT 300`

Add non-negative check constraints for lag and overlap. Existing rows derive their initial
watermark from the greatest known publication time for that target, falling back to the latest
discovery time when publication time is absent.

### `article_discovery`

Transform the existing `article_crawl_state` table in place so existing target/article
relationships survive:

- Rename the table to `article_discovery`.
- Rename `first_seen_at` to `discovered_at`.
- Keep `target_id`, `article_id`, and the composite primary key.
- Drop `url`, `content_hash`, `etag`, `last_modified`, `last_seen_at`, `last_changed_at`, and
  `last_change_type`.
- Replace state/change indexes and constraint names with discovery-oriented names.

The downgrade recreates nullable legacy columns with deterministic values where possible. It is
documented as structural rollback support, not restoration of historical change metadata.

### `crawl_run`

Add the three discovery counters, backfill existing records as:

```text
discovered_articles = new_articles + updated_articles + unchanged_articles
inserted_articles   = new_articles
duplicate_articles  = updated_articles + unchanged_articles
```

Then remove `new_articles`, `updated_articles`, and `unchanged_articles`.

## Domain

Split the domain by capability:

```text
domain/
  article/
  collection/
  crawling/
  authentication/
  enums.py
  errors.py
```

The new collection domain contains:

- `ArticleDiscovery`
- `CollectionWindow`
- `DiscoveryWindowPolicy`
- discovery-oriented `CrawlTarget`, `CrawlRun`, and result entities

`ArticleChangeDetector`, `ChangeType`, `ArticleCrawlState`, and change summaries are removed.
Pure URL normalization, link policy, and sensitive-value redaction remain domain-level policies.

## Application

Application code depends only on Domain and Application ports.

### Inbound ports

Move MCP/worker-facing protocols to `application/ports/inbound`:

- generic crawl use cases
- collection commands and queries
- authentication validation
- due-target execution

### Outbound ports

Move and regroup external contracts under `application/ports/outbound`:

- crawling/fetching
- extraction
- persistence and unit of work
- authentication profile, resolver, secret, and browser-session contracts
- browser lifecycle
- network/robots validation
- failure artifacts

### `ArticleCollectionService`

Replace `MonitoringService` and `ArticlePersistenceService` with a collection use case that:

1. claims a target lease;
2. reconciles stale runs;
3. calculates the discovery window;
4. starts lease heartbeat;
5. streams page observations from the crawler;
6. extracts and filters candidates by `published_at`;
7. inserts the global article with conflict-safe idempotency;
8. records the target/article discovery;
9. completes the run and advances the watermark in the same owner-fenced transaction;
10. records retry/backoff without allowing stale owners to finalize.

Duplicate URL reservation remains concurrency-safe and is released after persistence failures.

### `CollectionQueryService`

Owns target configuration, status queries, recent discovery queries, single-article retrieval, and
manual target execution. It replaces change-oriented query naming and DTOs.

## Adapters

Restructure adapters only after functional contracts and tests are green:

```text
adapters/
  inbound/
    mcp/
    worker/
  outbound/
    crawling/
    extraction/
    persistence/
    authentication/
    browser/
    network/
    artifacts/
```

Inbound adapters only validate/translate/invoke/serialize. Outbound adapters implement Application
ports. SQLAlchemy, Playwright, Crawlee, FastMCP, YAML, filesystem state, environment secrets, DNS,
and proxy details must not leak into Domain or collection use cases.

## Bootstrap

Replace the single `bootstrap.py` module and ambiguous `infrastructure` package with:

```text
bootstrap/
  container.py
  settings.py
  logging.py
  lifecycle.py
```

Bootstrap owns configuration, logging setup, dependency construction, and process lifecycle.
Concrete runtime implementations move to outbound adapters.

## MCP Contract

Keep:

- `scrape_page`
- `crawl_site`
- `validate_session`
- `list_supported_sites`
- `list_crawl_targets`
- `configure_crawl_target`
- `run_crawl_target`
- `get_crawl_status`
- `get_article`

Replace:

- `get_recent_article_changes` → `get_recent_articles`

`run_crawl_target` and status responses use discovered/inserted/duplicate counters. Target responses
include watermark, lag, and overlap configuration. This is an intentional breaking change approved
by choosing the new-only collection model.

## Error and Recovery Semantics

- Lease renewal errors fail closed.
- Only the current, unexpired owner may advance the watermark or finalize target/run state.
- Callback persistence failures fail the target run and trigger retry/backoff.
- A new claim reconciles prior `RUNNING` rows as `FAILED` with `lease_expired`.
- A failed or lease-lost run never advances the watermark.
- Per-page extraction failures remain isolated and contribute to `failed_pages`.

## Testing Strategy

Use failing tests before each behavior change.

- Domain tests for window boundaries, overlap, lag, and timezone normalization.
- Service tests for initial watermark, empty windows, dated/undated candidates, duplicates,
  successful advance, failed-run non-advance, heartbeat, fencing, and stale-run recovery.
- Repository tests for conflict-safe article insertion and discovery idempotency.
- Migration integration test from revision 02 with existing state/run rows, proving row and counter
  preservation after revision 03.
- MCP tests proving the new tool name and response fields and absence of change-oriented output.
- Import-boundary tests preventing Application imports from adapters/bootstrap.
- Full Ruff, format, mypy, unit, Playwright, and PostgreSQL integration gates.

## Documentation and Delivery

Update `README.md` with:

- architecture and directory map;
- local and Docker startup;
- migration command;
- target creation with watermark settings;
- worker and manual execution;
- status, recent article, and article-detail query examples;
- new-only semantics, overlap/lag explanation, and limitations for missing publication timestamps;
- validation commands.

After all checks pass, commit intentionally and push the verified head to GitHub `main` without
overwriting unrelated local worktree changes.
