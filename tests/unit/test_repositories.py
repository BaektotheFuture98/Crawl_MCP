from __future__ import annotations

from pathlib import Path

import pytest

from crawling_mcp.adapters.storage.file_repository import FileRepository
from crawling_mcp.adapters.storage.memory_repository import InMemoryRepository
from crawling_mcp.domain.enums import ErrorCode
from crawling_mcp.domain.models import CrawlFailure, CrawlResult, PageItem


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "file"])
async def test_repository_persists_job_pages_failures_and_completion(
    kind: str, tmp_path: Path
) -> None:
    repository = InMemoryRepository() if kind == "memory" else FileRepository(tmp_path / "results")
    job = CrawlResult(start_url="https://example.com")
    item = PageItem(url="https://example.com/one", title="One", content="body")
    failure = CrawlFailure(
        url="https://example.com/two",
        error_code=ErrorCode.NAVIGATION_ERROR,
        message="failed",
    )

    await repository.start_job(job)
    await repository.save_page(job.job_id, item)
    await repository.save_failure(job.job_id, failure)
    await repository.complete_job(job.job_id)
    stored = await repository.get_job(job.job_id)

    assert stored is not None
    assert stored.visited_pages == 2
    assert stored.succeeded_pages == 1
    assert stored.failed_pages == 1
    assert stored.items == [item]
    assert stored.failures == [failure]
    assert stored.completed_at is not None


@pytest.mark.asyncio
async def test_file_repository_writes_atomic_valid_json(tmp_path: Path) -> None:
    repository = FileRepository(tmp_path / "results")
    job = CrawlResult(start_url="https://example.com")

    await repository.start_job(job)
    await repository.save_page(job.job_id, PageItem(url="https://example.com"))

    result_file = tmp_path / "results" / f"{job.job_id}.json"
    assert result_file.is_file()
    assert not list((tmp_path / "results").glob("*.tmp"))
    assert CrawlResult.model_validate_json(result_file.read_text())
