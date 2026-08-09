from __future__ import annotations

from crawling_mcp.adapters.storage.postgres_repository import PostgresRepository
from crawling_mcp.bootstrap import build_container
from crawling_mcp.infrastructure.artifacts import MinioFailureArtifactWriter
from crawling_mcp.infrastructure.config import Settings


def test_bootstrap_selects_postgres_repository() -> None:
    container = build_container(
        Settings(
            repository="postgres",
            postgres_dsn="postgresql+asyncpg://crawler:secret@postgres:5432/crawling",
            minio_endpoint="minio:9000",
            minio_access_key="crawler",
            minio_secret_key="secret-key",
        )
    )

    assert isinstance(container.crawl_service._repository, PostgresRepository)
    assert isinstance(container.auth_service._artifacts, MinioFailureArtifactWriter)
