from __future__ import annotations

from pathlib import Path

import yaml


def test_compose_declares_services_and_isolated_data_volumes() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    assert set(compose["services"]) == {"mcp-server", "test-site"}
    assert set(compose["volumes"]) == {
        "auth-data",
        "results-data",
        "failures-data",
        "screenshots-data",
    }
    mounts = set(compose["services"]["mcp-server"]["volumes"])
    assert mounts == {
        "auth-data:/app/data/auth",
        "results-data:/app/data/results",
        "failures-data:/app/data/failures",
        "screenshots-data:/app/data/screenshots",
    }
    mcp = compose["services"]["mcp-server"]
    assert mcp["environment"]["CRAWLING_MCP_ALLOW_PRIVATE_NETWORKS"] == "false"
    assert "depends_on" not in mcp
    assert compose["services"]["test-site"]["profiles"] == ["test"]


def test_test_compose_override_scopes_private_access_to_test_site() -> None:
    override = yaml.safe_load(Path("docker-compose.test.yml").read_text(encoding="utf-8"))

    mcp = override["services"]["mcp-server"]
    assert mcp["environment"]["CRAWLING_MCP_ALLOW_PRIVATE_NETWORKS"] == "true"
    assert mcp["environment"]["CRAWLING_MCP_DOMAIN_ALLOWLIST"] == '["test-site"]'
    assert mcp["depends_on"]["test-site"]["condition"] == "service_healthy"


def test_dockerfile_uses_matching_playwright_image_and_non_root_user() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "mcr.microsoft.com/playwright/python:v1.62.0-noble" in dockerfile
    assert "USER crawling" in dockerfile
    assert 'ENTRYPOINT ["/app/.venv/bin/python", "-m", "crawling_mcp"]' in dockerfile


def test_project_declares_async_postgres_and_migration_dependencies() -> None:
    project = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '"sqlalchemy>=2.0,<3"' in project
    assert '"asyncpg>=0.30,<1"' in project
    assert '"alembic>=1.16,<2"' in project
