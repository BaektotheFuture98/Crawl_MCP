from __future__ import annotations

import inspect

from crawling_mcp.adapters.storage.postgres import (
    change_repository,
    snapshot_repository,
    target_repository,
)


def test_database_generated_ids_are_omitted_from_create_statements() -> None:
    sources = "\n".join(
        inspect.getsource(module)
        for module in (target_repository, snapshot_repository, change_repository)
    )

    assert "values(id=" not in sources
    assert (
        "RETURNING" not in sources
    )  # SQLAlchemy returning() is used, not hand-written UUID values
    assert ".returning(" in sources


def test_due_claims_use_postgres_skip_locked() -> None:
    source = inspect.getsource(target_repository.PostgresTargetRepository.claim_due)

    assert "skip_locked=True" in source
    assert "with_for_update" in source


def test_postgres_monitoring_responsibilities_are_split_by_module() -> None:
    assert hasattr(target_repository, "PostgresTargetRepository")
    assert hasattr(snapshot_repository, "PostgresSnapshotRepository")
    assert hasattr(change_repository, "PostgresChangeRepository")
