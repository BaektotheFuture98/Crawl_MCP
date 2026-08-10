"""Create PostgreSQL-only crawl monitoring storage."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260810_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB()
    op.create_table(
        "article",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.Text()),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("url", "content_hash", name="uq_article_url_content_hash"),
    )
    op.create_index("ix_article_source_published_at", "article", ["source", "published_at"])
    op.create_table(
        "crawl_targets",
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
        sa.CheckConstraint("interval_seconds >= 10", name="ck_crawl_targets_interval_positive"),
    )
    op.create_index(
        "ix_crawl_targets_due", "crawl_targets", ["enabled", "next_retry_at", "next_crawl_at"]
    )
    op.create_table(
        "crawl_jobs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("target_id", uuid, sa.ForeignKey("crawl_targets.id", ondelete="SET NULL")),
        sa.Column("start_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="RUNNING"),
        sa.Column("visited_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changed_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_crawl_jobs_target_started", "crawl_jobs", ["target_id", "started_at"])
    op.create_table(
        "crawl_job_pages",
        sa.Column(
            "crawl_job_id",
            uuid,
            sa.ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "article_id", uuid, sa.ForeignKey("article.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "crawl_failures",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "crawl_job_id", uuid, sa.ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("artifacts", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_crawl_failures_job", "crawl_failures", ["crawl_job_id"])
    op.create_table(
        "crawl_snapshots",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "target_id", uuid, sa.ForeignKey("crawl_targets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "article_id", uuid, sa.ForeignKey("article.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("etag", sa.Text()),
        sa.Column("last_modified", sa.Text()),
        sa.Column("metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("target_id", "url", "content_hash", name="uq_snapshot_version"),
    )
    op.create_index(
        "ix_crawl_snapshots_latest", "crawl_snapshots", ["target_id", "url", "collected_at"]
    )
    op.create_table(
        "crawl_changes",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "target_id", uuid, sa.ForeignKey("crawl_targets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("change_type", sa.String(16), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "previous_snapshot_id", uuid, sa.ForeignKey("crawl_snapshots.id", ondelete="SET NULL")
        ),
        sa.Column(
            "current_snapshot_id",
            uuid,
            sa.ForeignKey("crawl_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crawl_changes_recent", "crawl_changes", ["detected_at"])
    op.create_index("ix_crawl_changes_target_recent", "crawl_changes", ["target_id", "detected_at"])


def downgrade() -> None:
    op.drop_table("crawl_changes")
    op.drop_table("crawl_snapshots")
    op.drop_table("crawl_failures")
    op.drop_table("crawl_job_pages")
    op.drop_table("crawl_jobs")
    op.drop_table("crawl_targets")
    op.drop_table("article")
