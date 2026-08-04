from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(env_prefix="CRAWLING_MCP_", env_file=".env", extra="ignore")

    log_level: str = "INFO"
    repository: str = "file"
    data_dir: Path = Path("data")
    auth_profiles_path: Path = Path("config/auth_profiles.yaml")
    allow_private_networks: bool = False
    domain_allowlist: list[str] = Field(default_factory=list)
    browser_headless: bool = True
    browser_max_contexts: int = Field(default=3, ge=1, le=20)
