from __future__ import annotations

import pytest

from crawling_mcp.adapters.storage.memory_repository import InMemoryRepository
from crawling_mcp.adapters.storage.monitoring_memory import InMemoryMonitoringStore
from crawling_mcp.adapters.storage.postgres import PostgresMonitoringStore
from crawling_mcp.bootstrap import build_container, build_worker_container
from crawling_mcp.infrastructure.config import Settings


def test_memory_container_wires_monitoring_services_without_changing_crawl_repository() -> None:
    container = build_container(Settings(_env_file=None, repository="memory"))

    assert isinstance(container.monitoring_store, InMemoryMonitoringStore)
    assert container.monitoring_service is not None
    assert container.monitoring_query_service is not None


def test_postgres_container_shares_postgres_adapters_without_minio() -> None:
    container = build_container(Settings(_env_file=None, repository="postgres"))

    assert isinstance(container.crawl_service._repository, InMemoryRepository)
    assert isinstance(container.monitoring_store, PostgresMonitoringStore)


def test_worker_requires_shared_postgres_storage() -> None:
    with pytest.raises(ValueError, match="postgres"):
        build_worker_container(Settings(_env_file=None, repository="file"))
