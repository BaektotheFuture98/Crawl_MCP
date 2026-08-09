"""Create append-only crawl job, article and failure storage."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260810_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("start_url", sa.Text(), nullable=False),
        sa.Column("visited_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "crawl_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("raw_html_key", sa.Text(), nullable=False),
        sa.Column("raw_html_uri", sa.Text(), nullable=False),
        sa.Column("raw_html_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_html_size_bytes", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_articles_crawl_job_id", "articles", ["crawl_job_id"])
    op.create_index("ix_articles_url", "articles", ["url"])
    op.create_index("ix_articles_canonical_url", "articles", ["canonical_url"])
    op.create_index("ix_articles_source_published_at", "articles", ["source", "published_at"])
    op.create_table(
        "crawl_failures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "crawl_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "artifacts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_crawl_failures_crawl_job_id", "crawl_failures", ["crawl_job_id"])


def downgrade() -> None:
    op.drop_index("ix_crawl_failures_crawl_job_id", table_name="crawl_failures")
    op.drop_table("crawl_failures")
    op.drop_index("ix_articles_source_published_at", table_name="articles")
    op.drop_index("ix_articles_canonical_url", table_name="articles")
    op.drop_index("ix_articles_url", table_name="articles")
    op.drop_index("ix_articles_crawl_job_id", table_name="articles")
    op.drop_table("articles")
    op.drop_table("crawl_jobs")
