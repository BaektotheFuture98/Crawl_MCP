"""Add crawler state around the existing public ARTICLE table."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260810_01"
down_revision = None
branch_labels = None
depends_on = None


def _validate_article() -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "article" not in inspector.get_table_names():
        raise RuntimeError("existing ARTICLE table is required; this migration does not create it")
    columns = {column["name"]: column for column in inspector.get_columns("article")}
    required = {
        "id",
        "ar_title",
        "ar_content",
        "reporter",
        "publisher",
        "url",
        "published_at",
    }
    missing = required - set(columns)
    if missing:
        raise RuntimeError(f"existing ARTICLE table is missing columns: {sorted(missing)}")
    if "uuidv7" not in str(columns["id"].get("default", "")).lower():
        raise RuntimeError("existing ARTICLE.id must use database DEFAULT uuidv7()")
    duplicate = bind.execute(
        sa.text(
            "SELECT url, count(*) FROM article WHERE url IS NOT NULL "
            "GROUP BY url HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "ARTICLE contains duplicate URLs; merge or remove duplicates before migration: "
            f"{duplicate[0]!r} ({duplicate[1]} rows)"
        )
    unique_index = any(
        bool(index.get("unique")) and index.get("column_names") == ["url"]
        for index in inspector.get_indexes("article")
    )
    unique_constraint = any(
        constraint.get("column_names") == ["url"]
        for constraint in inspector.get_unique_constraints("article")
    )
    return unique_index or unique_constraint


def upgrade() -> None:
    article_url_is_unique = _validate_article()
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB()
    if not article_url_is_unique:
        op.create_index("uq_article_url_monitoring", "article", ["url"], unique=True)
    op.create_table(
        "crawl_target",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("crawl_mode", sa.String(16), nullable=False),
        sa.Column("auth_profile", sa.String(128)),
        sa.Column("crawl_options", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True)),
        sa.Column("next_crawl_at", sa.DateTime(timezone=True)),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_failed_at", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("interval_seconds >= 10", name="ck_crawl_target_interval_positive"),
    )
    op.create_index(
        "ix_crawl_target_due", "crawl_target", ["enabled", "next_retry_at", "next_crawl_at"]
    )
    op.create_table(
        "article_crawl_state",
        sa.Column(
            "article_id",
            uuid,
            sa.ForeignKey("article.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "target_id",
            uuid,
            sa.ForeignKey("crawl_target.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("etag", sa.Text()),
        sa.Column("last_modified", sa.Text()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(timezone=True)),
        sa.Column("last_change_type", sa.String(16)),
    )
    op.create_index(
        "ix_article_crawl_state_recent",
        "article_crawl_state",
        ["last_changed_at", "last_change_type"],
    )
    op.create_index(
        "ix_article_crawl_state_target",
        "article_crawl_state",
        ["target_id", "last_seen_at"],
    )
    op.create_table(
        "crawl_run",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "target_id",
            uuid,
            sa.ForeignKey("crawl_target.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("visited_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_articles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_articles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_articles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_crawl_run_target_started", "crawl_run", ["target_id", "started_at"])


def downgrade() -> None:
    op.drop_table("crawl_run")
    op.drop_table("article_crawl_state")
    op.drop_table("crawl_target")
    op.execute(sa.text("DROP INDEX IF EXISTS uq_article_url_monitoring"))
