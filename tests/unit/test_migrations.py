from __future__ import annotations

from pathlib import Path

from crawling_mcp.adapters.storage.postgres.schema import metadata


def test_schema_contains_focused_monitoring_tables_and_indexes() -> None:
    assert set(metadata.tables) == {
        "article",
        "crawl_changes",
        "crawl_failures",
        "crawl_job_pages",
        "crawl_jobs",
        "crawl_snapshots",
        "crawl_targets",
    }
    targets = metadata.tables["crawl_targets"]
    assert {"lease_owner", "lease_expires_at", "next_retry_at", "failure_count"} <= set(
        targets.columns.keys()
    )
    assert metadata.tables["crawl_snapshots"].c.article_id.foreign_keys
    assert metadata.tables["crawl_changes"].c.current_snapshot_id.foreign_keys


def test_migration_uses_database_uuidv7_and_has_reversible_tables() -> None:
    migration = Path("alembic/versions/20260810_01_continuous_monitoring.py").read_text(
        encoding="utf-8"
    )

    assert migration.count("uuidv7()") >= 4
    assert "article" in migration
    assert "crawl_targets" in migration
    assert "crawl_snapshots" in migration
    assert "crawl_changes" in migration
    assert "def downgrade()" in migration
    assert "minio" not in migration.lower()


def test_database_generated_entities_have_uuidv7_defaults() -> None:
    for table_name in ("article", "crawl_targets", "crawl_snapshots", "crawl_changes"):
        default = metadata.tables[table_name].c.id.server_default
        assert default is not None
        assert "uuidv7()" in str(default.arg)
