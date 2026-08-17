"""Scope article crawl state by target and article."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260817_02"
down_revision = "20260810_01"
branch_labels = None
depends_on = None


def _primary_key_name() -> str:
    value = sa.inspect(op.get_bind()).get_pk_constraint("article_crawl_state").get("name")
    if not isinstance(value, str) or not value:
        raise RuntimeError("article_crawl_state primary key name could not be resolved")
    return value


def _global_url_constraint_name() -> str:
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("article_crawl_state")
    for constraint in constraints:
        if constraint.get("column_names") == ["url"]:
            name = constraint.get("name")
            if isinstance(name, str) and name:
                return name
    raise RuntimeError("article_crawl_state global URL constraint could not be resolved")


def upgrade() -> None:
    op.drop_constraint(_primary_key_name(), "article_crawl_state", type_="primary")
    op.drop_constraint(
        _global_url_constraint_name(),
        "article_crawl_state",
        type_="unique",
    )
    op.create_primary_key(
        "pk_article_crawl_state",
        "article_crawl_state",
        ["target_id", "article_id"],
    )
    op.create_unique_constraint(
        "uq_article_crawl_state_target_url",
        "article_crawl_state",
        ["target_id", "url"],
    )


def downgrade() -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            "SELECT article_id, count(*) FROM article_crawl_state "
            "GROUP BY article_id HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "cannot restore global article state while an article belongs to multiple targets: "
            f"{duplicate[0]} ({duplicate[1]} rows)"
        )
    op.drop_constraint(
        "uq_article_crawl_state_target_url",
        "article_crawl_state",
        type_="unique",
    )
    op.drop_constraint("pk_article_crawl_state", "article_crawl_state", type_="primary")
    op.create_primary_key(
        "pk_article_crawl_state",
        "article_crawl_state",
        ["article_id"],
    )
    op.create_unique_constraint(
        "uq_article_crawl_state_url",
        "article_crawl_state",
        ["url"],
    )
