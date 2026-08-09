from __future__ import annotations

from crawling_mcp.infrastructure.config import Settings


def test_settings_supports_postgres_and_minio_storage_configuration() -> None:
    settings = Settings(
        repository="postgres",
        postgres_dsn="postgresql+asyncpg://crawler:secret@postgres:5432/crawling",
        minio_endpoint="minio:9000",
        minio_access_key="crawler",
        minio_secret_key="secret-key",
        minio_bucket="crawl-data",
        minio_secure=False,
    )

    assert settings.repository == "postgres"
    assert settings.postgres_dsn.startswith("postgresql+asyncpg://")
    assert settings.minio_endpoint == "minio:9000"
    assert settings.minio_bucket == "crawl-data"
    assert settings.minio_secure is False
