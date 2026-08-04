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


def test_dockerfile_uses_matching_playwright_image_and_non_root_user() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "mcr.microsoft.com/playwright/python:v1.62.0-noble" in dockerfile
    assert "USER crawling" in dockerfile
    assert 'ENTRYPOINT ["/app/.venv/bin/python", "-m", "crawling_mcp"]' in dockerfile
