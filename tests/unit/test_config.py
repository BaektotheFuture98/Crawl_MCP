from __future__ import annotations

import pytest

from crawling_mcp.bootstrap.config import Settings


def test_postgres_and_worker_settings_have_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.postgres_dsn.startswith("postgresql+asyncpg://")
    assert settings.worker_poll_interval_seconds == 5.0
    assert settings.worker_batch_size == 10
    assert settings.worker_lease_seconds == 600
    assert settings.worker_retry_base_seconds == 30
    assert settings.worker_retry_max_seconds == 3600


def test_postgres_repository_is_supported() -> None:
    settings = Settings(_env_file=None, repository="postgres")

    assert settings.repository == "postgres"


def test_database_url_alias_configures_existing_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:secret@db.example/news")

    settings = Settings(_env_file=None)

    assert settings.postgres_dsn == "postgresql+asyncpg://app:secret@db.example/news"
