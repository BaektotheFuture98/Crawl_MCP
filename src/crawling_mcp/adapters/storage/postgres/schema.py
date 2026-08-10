from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

uuid_type = postgresql.UUID(as_uuid=True)
json_type = postgresql.JSONB()
uuidv7_default = sa.text("uuidv7()")
now_default = sa.text("CURRENT_TIMESTAMP")

article = sa.Table(
    "article",
    metadata,
    sa.Column("id", uuid_type, primary_key=True, server_default=uuidv7_default),
    sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("title", sa.Text(), nullable=False),
    sa.Column("content", sa.Text(), nullable=False),
    sa.Column("source", sa.Text(), nullable=True),
    sa.Column("url", sa.Text(), nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint("url", "content_hash", name="uq_article_url_content_hash"),
)
sa.Index("ix_article_source_published_at", article.c.source, article.c.published_at)

crawl_targets = sa.Table(
    "crawl_targets",
    metadata,
    sa.Column("id", uuid_type, primary_key=True, server_default=uuidv7_default),
    sa.Column("url", sa.Text(), nullable=False, unique=True),
    sa.Column("interval_seconds", sa.Integer(), nullable=False),
    sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("crawl_mode", sa.String(16), nullable=False),
    sa.Column("auth_profile", sa.String(128), nullable=True),
    sa.Column("crawl_options", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now_default),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now_default),
    sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("next_crawl_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("last_error", sa.Text(), nullable=True),
    sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("lease_owner", sa.String(128), nullable=True),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("interval_seconds >= 10", name="interval_positive"),
)
sa.Index(
    "ix_crawl_targets_due",
    crawl_targets.c.enabled,
    crawl_targets.c.next_retry_at,
    crawl_targets.c.next_crawl_at,
)

crawl_jobs = sa.Table(
    "crawl_jobs",
    metadata,
    sa.Column("id", uuid_type, primary_key=True),
    sa.Column(
        "target_id",
        uuid_type,
        sa.ForeignKey("crawl_targets.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column("start_url", sa.Text(), nullable=False),
    sa.Column("status", sa.String(16), nullable=False, server_default="RUNNING"),
    sa.Column("visited_pages", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("succeeded_pages", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("failed_pages", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("changed_pages", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("new_pages", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("updated_pages", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("unchanged_pages", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("error", sa.Text(), nullable=True),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
)
sa.Index("ix_crawl_jobs_target_started", crawl_jobs.c.target_id, crawl_jobs.c.started_at)

crawl_job_pages = sa.Table(
    "crawl_job_pages",
    metadata,
    sa.Column(
        "crawl_job_id",
        uuid_type,
        sa.ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "article_id",
        uuid_type,
        sa.ForeignKey("article.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    sa.Column("url", sa.Text(), nullable=False),
    sa.Column("metadata", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
)

crawl_failures = sa.Table(
    "crawl_failures",
    metadata,
    sa.Column("id", uuid_type, primary_key=True, server_default=uuidv7_default),
    sa.Column(
        "crawl_job_id",
        uuid_type,
        sa.ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("url", sa.Text(), nullable=False),
    sa.Column("error_code", sa.String(64), nullable=False),
    sa.Column("message", sa.Text(), nullable=False),
    sa.Column("details", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("artifacts", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now_default),
)
sa.Index("ix_crawl_failures_job", crawl_failures.c.crawl_job_id)

crawl_snapshots = sa.Table(
    "crawl_snapshots",
    metadata,
    sa.Column("id", uuid_type, primary_key=True, server_default=uuidv7_default),
    sa.Column(
        "target_id",
        uuid_type,
        sa.ForeignKey("crawl_targets.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "article_id",
        uuid_type,
        sa.ForeignKey("article.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("url", sa.Text(), nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("etag", sa.Text(), nullable=True),
    sa.Column("last_modified", sa.Text(), nullable=True),
    sa.Column("metadata", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("target_id", "url", "content_hash", name="uq_snapshot_version"),
)
sa.Index(
    "ix_crawl_snapshots_latest",
    crawl_snapshots.c.target_id,
    crawl_snapshots.c.url,
    crawl_snapshots.c.collected_at,
)

crawl_changes = sa.Table(
    "crawl_changes",
    metadata,
    sa.Column("id", uuid_type, primary_key=True, server_default=uuidv7_default),
    sa.Column(
        "target_id",
        uuid_type,
        sa.ForeignKey("crawl_targets.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("change_type", sa.String(16), nullable=False),
    sa.Column("url", sa.Text(), nullable=False),
    sa.Column("title", sa.Text(), nullable=False, server_default=""),
    sa.Column(
        "previous_snapshot_id",
        uuid_type,
        sa.ForeignKey("crawl_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column(
        "current_snapshot_id",
        uuid_type,
        sa.ForeignKey("crawl_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
)
sa.Index("ix_crawl_changes_recent", crawl_changes.c.detected_at)
sa.Index("ix_crawl_changes_target_recent", crawl_changes.c.target_id, crawl_changes.c.detected_at)
