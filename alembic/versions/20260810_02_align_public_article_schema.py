"""Align crawl persistence with the existing public ARTICLE contract."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260810_02"
down_revision = "20260810_01"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _require_uuidv7() -> None:
    bind = op.get_bind()
    has_uuidv7 = bind.execute(sa.text("SELECT to_regprocedure('uuidv7()') IS NOT NULL")).scalar()
    if not has_uuidv7:
        raise RuntimeError("article.id requires a database-provided uuidv7() function")


def _validate_existing_article() -> None:
    columns = {
        column["name"]: column for column in sa.inspect(op.get_bind()).get_columns("article")
    }
    expected = {
        "id",
        "ar_title",
        "ar_content",
        "reporter",
        "publisher",
        "url",
        "published_at",
    }
    missing = expected - set(columns)
    if missing:
        raise RuntimeError(f"existing article table is missing columns: {sorted(missing)}")
    if "uuidv7" not in str(columns["id"].get("default", "")).lower():
        raise RuntimeError("existing article.id must use the database DEFAULT uuidv7()")


def upgrade() -> None:
    tables = _tables()
    if "article" not in tables:
        _require_uuidv7()
        op.create_table(
            "article",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("uuidv7()"),
            ),
            sa.Column("ar_title", sa.Text(), nullable=True),
            sa.Column("ar_content", sa.Text(), nullable=True),
            sa.Column("reporter", sa.String(length=100), nullable=True),
            sa.Column("publisher", sa.String(length=100), nullable=True),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=False), nullable=True),
        )
    else:
        _validate_existing_article()

    op.create_table(
        "crawl_page_commits",
        sa.Column(
            "crawl_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("page_key", sa.String(length=64), primary_key=True),
        sa.Column(
            "committed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "crawl_article_objects",
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("article.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "crawl_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meta_description", sa.Text(), nullable=True),
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
    op.create_index(
        "ix_crawl_article_objects_crawl_job_id",
        "crawl_article_objects",
        ["crawl_job_id"],
    )
    op.create_index("ix_article_url", "article", ["url"])
    op.create_index("ix_article_publisher_published_at", "article", ["publisher", "published_at"])

    if "articles" in tables:
        op.execute(
            sa.text(
                """
                INSERT INTO article (
                    id, ar_title, ar_content, reporter, publisher, url, published_at
                )
                SELECT id, title, content, NULL, source, url,
                       published_at AT TIME ZONE 'Asia/Seoul'
                FROM articles
                """
            )
        )
        op.execute(
            sa.text(
                """
                INSERT INTO crawl_article_objects (
                    article_id, crawl_job_id, collected_at, canonical_url,
                    http_status_code, language, metadata, raw_html_key, raw_html_uri,
                    raw_html_sha256, raw_html_size_bytes
                )
                SELECT id, crawl_job_id, collected_at, canonical_url,
                       http_status_code, language, metadata, raw_html_key, raw_html_uri,
                       raw_html_sha256, raw_html_size_bytes
                FROM articles
                """
            )
        )
        op.drop_table("articles")


def downgrade() -> None:
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
    op.execute(
        sa.text(
            """
            INSERT INTO articles (
                id, crawl_job_id, collected_at, published_at, title, content, source,
                url, canonical_url, http_status_code, language, metadata,
                raw_html_key, raw_html_uri, raw_html_sha256, raw_html_size_bytes
            )
            SELECT a.id, o.crawl_job_id, o.collected_at,
                   a.published_at AT TIME ZONE 'Asia/Seoul', a.ar_title, a.ar_content,
                   a.publisher, a.url, o.canonical_url, o.http_status_code, o.language,
                   o.metadata, o.raw_html_key, o.raw_html_uri, o.raw_html_sha256,
                   o.raw_html_size_bytes
            FROM article AS a
            JOIN crawl_article_objects AS o ON o.article_id = a.id
            """
        )
    )
    op.create_index("ix_articles_crawl_job_id", "articles", ["crawl_job_id"])
    op.create_index("ix_articles_url", "articles", ["url"])
    op.create_index("ix_articles_canonical_url", "articles", ["canonical_url"])
    op.create_index(
        "ix_articles_source_published_at",
        "articles",
        ["source", "published_at"],
    )
    op.drop_index("ix_article_publisher_published_at", table_name="article")
    op.drop_index("ix_article_url", table_name="article")
    op.drop_index("ix_crawl_article_objects_crawl_job_id", table_name="crawl_article_objects")
    op.drop_table("crawl_article_objects")
    op.drop_table("crawl_page_commits")
