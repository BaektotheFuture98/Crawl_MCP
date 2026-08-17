"""Replace article change state with publication-time discovery state."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260817_03"
down_revision = "20260817_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crawl_target", sa.Column("discovery_watermark_at", sa.DateTime(timezone=True)))
    op.add_column(
        "crawl_target",
        sa.Column("discovery_lag_seconds", sa.Integer(), nullable=False, server_default="30"),
    )
    op.add_column(
        "crawl_target",
        sa.Column("discovery_overlap_seconds", sa.Integer(), nullable=False, server_default="300"),
    )
    op.create_check_constraint(
        "ck_crawl_target_discovery_lag_non_negative",
        "crawl_target",
        "discovery_lag_seconds >= 0",
    )
    op.create_check_constraint(
        "ck_crawl_target_discovery_overlap_non_negative",
        "crawl_target",
        "discovery_overlap_seconds >= 0",
    )
    op.execute(
        sa.text(
            """
            UPDATE crawl_target AS target
            SET discovery_watermark_at = source.watermark
            FROM (
                SELECT state.target_id,
                       COALESCE(
                           MAX(article.published_at AT TIME ZONE 'Asia/Seoul'),
                           MAX(state.first_seen_at)
                       ) AS watermark
                FROM article_crawl_state AS state
                JOIN article ON article.id = state.article_id
                GROUP BY state.target_id
            ) AS source
            WHERE target.id = source.target_id
            """
        )
    )

    op.add_column(
        "crawl_run",
        sa.Column("discovered_articles", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "crawl_run",
        sa.Column("inserted_articles", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "crawl_run",
        sa.Column("duplicate_articles", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        sa.text(
            """
            UPDATE crawl_run
            SET discovered_articles = new_articles + updated_articles + unchanged_articles,
                inserted_articles = new_articles,
                duplicate_articles = updated_articles + unchanged_articles
            """
        )
    )
    op.drop_column("crawl_run", "unchanged_articles")
    op.drop_column("crawl_run", "updated_articles")
    op.drop_column("crawl_run", "new_articles")

    op.drop_index("ix_article_crawl_state_recent", table_name="article_crawl_state")
    op.drop_index("ix_article_crawl_state_target", table_name="article_crawl_state")
    op.drop_constraint("uq_article_crawl_state_target_url", "article_crawl_state", type_="unique")
    op.drop_constraint("pk_article_crawl_state", "article_crawl_state", type_="primary")
    op.rename_table("article_crawl_state", "article_discovery")
    op.alter_column("article_discovery", "first_seen_at", new_column_name="discovered_at")
    for column in (
        "url",
        "content_hash",
        "etag",
        "last_modified",
        "last_seen_at",
        "last_changed_at",
        "last_change_type",
    ):
        op.drop_column("article_discovery", column)
    op.create_primary_key("pk_article_discovery", "article_discovery", ["target_id", "article_id"])
    op.create_index(
        "ix_article_discovery_target_discovered",
        "article_discovery",
        ["target_id", "discovered_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_article_discovery_target_discovered", table_name="article_discovery")
    op.drop_constraint("pk_article_discovery", "article_discovery", type_="primary")
    op.add_column("article_discovery", sa.Column("url", sa.Text()))
    op.add_column("article_discovery", sa.Column("content_hash", sa.String(64)))
    op.add_column("article_discovery", sa.Column("etag", sa.Text()))
    op.add_column("article_discovery", sa.Column("last_modified", sa.Text()))
    op.add_column("article_discovery", sa.Column("last_seen_at", sa.DateTime(timezone=True)))
    op.add_column("article_discovery", sa.Column("last_changed_at", sa.DateTime(timezone=True)))
    op.add_column("article_discovery", sa.Column("last_change_type", sa.String(16)))
    op.execute(
        sa.text(
            """
            UPDATE article_discovery AS discovery
            SET url = article.url,
                content_hash = md5(
                                   COALESCE(article.ar_title, '')
                                   || COALESCE(article.ar_content, '')
                               )
                               || md5(COALESCE(article.url, '')),
                last_seen_at = discovery.discovered_at,
                last_changed_at = discovery.discovered_at,
                last_change_type = 'NEW'
            FROM article
            WHERE article.id = discovery.article_id
            """
        )
    )
    op.alter_column("article_discovery", "url", nullable=False)
    op.alter_column("article_discovery", "content_hash", nullable=False)
    op.alter_column("article_discovery", "last_seen_at", nullable=False)
    op.alter_column("article_discovery", "discovered_at", new_column_name="first_seen_at")
    op.rename_table("article_discovery", "article_crawl_state")
    op.create_primary_key(
        "pk_article_crawl_state", "article_crawl_state", ["target_id", "article_id"]
    )
    op.create_unique_constraint(
        "uq_article_crawl_state_target_url",
        "article_crawl_state",
        ["target_id", "url"],
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

    op.add_column(
        "crawl_run", sa.Column("new_articles", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "crawl_run",
        sa.Column("updated_articles", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "crawl_run",
        sa.Column("unchanged_articles", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        sa.text(
            """
            UPDATE crawl_run
            SET new_articles = inserted_articles,
                updated_articles = 0,
                unchanged_articles = duplicate_articles
            """
        )
    )
    op.drop_column("crawl_run", "duplicate_articles")
    op.drop_column("crawl_run", "inserted_articles")
    op.drop_column("crawl_run", "discovered_articles")

    op.drop_constraint(
        "ck_crawl_target_discovery_overlap_non_negative", "crawl_target", type_="check"
    )
    op.drop_constraint("ck_crawl_target_discovery_lag_non_negative", "crawl_target", type_="check")
    op.drop_column("crawl_target", "discovery_overlap_seconds")
    op.drop_column("crawl_target", "discovery_lag_seconds")
    op.drop_column("crawl_target", "discovery_watermark_at")
