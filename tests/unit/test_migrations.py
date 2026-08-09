from __future__ import annotations

from pathlib import Path


def test_latest_migration_targets_public_article_contract_and_sidecar() -> None:
    migration = Path("alembic/versions/20260810_02_align_public_article_schema.py").read_text(
        encoding="utf-8"
    )

    for name in (
        '"article"',
        '"ar_title"',
        '"ar_content"',
        '"reporter"',
        '"publisher"',
        '"url"',
        '"published_at"',
        '"crawl_article_objects"',
        '"crawl_page_commits"',
        'server_default=sa.text("uuidv7()")',
    ):
        assert name in migration
