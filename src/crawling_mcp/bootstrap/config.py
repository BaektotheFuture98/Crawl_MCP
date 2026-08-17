from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(env_prefix="CRAWLING_MCP_", env_file=".env", extra="ignore")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    repository: Literal["memory", "file", "postgres"] = "file"
    data_dir: Path = Path("data")
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://crawler:crawler@127.0.0.1:54329/crawling",
        validation_alias=AliasChoices("CRAWLING_MCP_POSTGRES_DSN", "DATABASE_URL"),
    )
    worker_poll_interval_seconds: float = Field(default=5.0, gt=0, le=300)
    worker_batch_size: int = Field(default=10, ge=1, le=100)
    worker_lease_seconds: int = Field(default=600, ge=30, le=86_400)
    worker_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    worker_retry_max_seconds: int = Field(default=3600, ge=1, le=86_400)
    auth_profiles_path: Path = Path("config/auth_profiles.yaml")
    allow_private_networks: bool = False
    domain_allowlist: list[str] = Field(default_factory=list)
    browser_headless: bool = True
    browser_max_contexts: int = Field(default=3, ge=1, le=20)
    max_pages_limit: int = Field(default=500, ge=1, le=500)
    max_depth_limit: int = Field(default=10, ge=0, le=10)
    max_request_retries_limit: int = Field(default=5, ge=0, le=5)
    request_timeout_limit_seconds: int = Field(default=120, ge=1, le=120)
    job_timeout_limit_seconds: int = Field(default=3600, ge=1, le=3600)
    max_concurrency_limit: int = Field(default=20, ge=1, le=20)
    max_content_bytes: int = Field(default=10_000_000, ge=1024, le=100_000_000)
    max_links_per_page: int = Field(default=1000, ge=1, le=10_000)
    max_dns_answers: int = Field(default=16, ge=1, le=64)
    egress_connect_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    max_egress_bytes_per_connection: int = Field(
        default=25_000_000,
        ge=1024,
        le=500_000_000,
    )
    dns_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    test_site_base_url: str = "http://127.0.0.1:8765"
