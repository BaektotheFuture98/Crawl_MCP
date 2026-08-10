from __future__ import annotations

import asyncio

from crawling_mcp.adapters.worker.runner import run_worker
from crawling_mcp.infrastructure.config import Settings
from crawling_mcp.infrastructure.logging import configure_logging


def main() -> None:
    """Run the continuous crawler worker process."""
    settings = Settings()
    configure_logging(settings.log_level)
    asyncio.run(run_worker(settings=settings))


if __name__ == "__main__":
    main()
