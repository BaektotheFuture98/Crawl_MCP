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

# Existing externally-owned final table. Alembic validates but never creates or drops it.
article = sa.Table(
    "article",
    metadata,
    sa.Column("id", uuid_type, primary_key=True, server_default=uuidv7_default),
    sa.Column("ar_title", sa.Text(), nullable=True),
    sa.Column("ar_content", sa.Text(), nullable=True),
    sa.Column("reporter", sa.String(100), nullable=True),
    sa.Column("publisher", sa.String(100), nullable=True),
    sa.Column("url", sa.Text(), nullable=True),
    sa.Column("published_at", sa.DateTime(timezone=False), nullable=True),
)

crawl_target = sa.Table(
    "crawl_target",
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
    sa.Column("discovery_watermark_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("discovery_lag_seconds", sa.Integer(), nullable=False, server_default="30"),
    sa.Column("discovery_overlap_seconds", sa.Integer(), nullable=False, server_default="300"),
    sa.CheckConstraint("interval_seconds >= 10", name="interval_positive"),
    sa.CheckConstraint("discovery_lag_seconds >= 0", name="discovery_lag_non_negative"),
    sa.CheckConstraint("discovery_overlap_seconds >= 0", name="discovery_overlap_non_negative"),
)
sa.Index(
    "ix_crawl_target_due",
    crawl_target.c.enabled,
    crawl_target.c.next_retry_at,
    crawl_target.c.next_crawl_at,
)

article_discovery = sa.Table(
    "article_discovery",
    metadata,
    sa.Column(
        "article_id",
        uuid_type,
        sa.ForeignKey("article.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "target_id",
        uuid_type,
        sa.ForeignKey("crawl_target.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("target_id", "article_id", name="pk_article_discovery"),
)
sa.Index(
    "ix_article_discovery_target_discovered",
    article_discovery.c.target_id,
    article_discovery.c.discovered_at,
)

crawl_run = sa.Table(
    "crawl_run",
    metadata,
    sa.Column("id", uuid_type, primary_key=True, server_default=uuidv7_default),
    sa.Column(
        "target_id",
        uuid_type,
        sa.ForeignKey("crawl_target.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("visited_pages", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("discovered_articles", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("inserted_articles", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("duplicate_articles", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("failed_pages", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("error", sa.Text(), nullable=True),
)
sa.Index("ix_crawl_run_target_started", crawl_run.c.target_id, crawl_run.c.started_at)
