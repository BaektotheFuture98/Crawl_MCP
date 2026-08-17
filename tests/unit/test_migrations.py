from __future__ import annotations

from pathlib import Path

from crawling_mcp.adapters.storage.postgres.schema import metadata


def test_schema_keeps_exact_article_contract_and_only_three_state_tables() -> None:
    assert set(metadata.tables) == {
        "article",
        "article_crawl_state",
        "crawl_run",
        "crawl_target",
    }
    assert set(metadata.tables["article"].columns.keys()) == {
        "id",
        "ar_title",
        "ar_content",
        "reporter",
        "publisher",
        "url",
        "published_at",
    }
    assert "ar_content" not in metadata.tables["article_crawl_state"].columns


def test_migration_validates_but_never_creates_or_drops_article() -> None:
    migration = Path("alembic/versions/20260810_01_continuous_monitoring.py").read_text()

    assert 'op.create_table(\n        "article"' not in migration
    assert 'op.drop_table("article")' not in migration
    assert "existing ARTICLE table is required" in migration
    assert "duplicate URLs" in migration
    assert 'op.create_table(\n        "crawl_target"' in migration
    assert 'op.create_table(\n        "article_crawl_state"' in migration
    assert 'op.create_table(\n        "crawl_run"' in migration
    assert "crawl_snapshot" not in migration
    assert "minio" not in migration.lower()


def test_only_crawler_owned_uuid_ids_have_database_defaults() -> None:
    for table_name in ("article", "crawl_target", "crawl_run"):
        default = metadata.tables[table_name].c.id.server_default
        assert default is not None and "uuidv7()" in str(default.arg)


def test_article_state_identity_is_scoped_to_target_and_article() -> None:
    state = metadata.tables["article_crawl_state"]

    assert [column.name for column in state.primary_key.columns] == ["target_id", "article_id"]
    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in state.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("target_id", "url") in unique_column_sets
    assert ("url",) not in unique_column_sets
