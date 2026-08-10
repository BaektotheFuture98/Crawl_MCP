from __future__ import annotations

import inspect

from crawling_mcp.adapters.storage.postgres import (
    article_repository,
    run_repository,
    state_repository,
    target_repository,
)


def test_database_owned_ids_are_never_supplied_by_repository_inserts() -> None:
    sources = "\n".join(
        inspect.getsource(module)
        for module in (article_repository, run_repository, state_repository, target_repository)
    )

    assert "values(id=" not in sources
    assert ".returning(" in sources


def test_due_and_manual_claims_use_postgres_skip_locked() -> None:
    due = inspect.getsource(target_repository.PostgresTargetRepository.claim_due)
    manual = inspect.getsource(target_repository.PostgresTargetRepository.claim)

    assert "skip_locked=True" in due and "with_for_update" in due
    assert "skip_locked=True" in manual and "with_for_update" in manual


def test_postgres_responsibilities_are_split_by_module() -> None:
    assert hasattr(article_repository, "PostgresArticleRepository")
    assert hasattr(state_repository, "PostgresArticleCrawlStateRepository")
    assert hasattr(run_repository, "PostgresCrawlRunRepository")
    assert hasattr(target_repository, "PostgresTargetRepository")
