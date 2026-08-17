from __future__ import annotations

import asyncio

from crawling_mcp.adapters.inbound.worker.runner import run_worker
from crawling_mcp.bootstrap import build_worker_container
from crawling_mcp.bootstrap.config import Settings
from crawling_mcp.bootstrap.logging import configure_logging


def main() -> None:
    """Run the continuous crawler worker process."""
    settings = Settings()
    configure_logging(settings.log_level)
    asyncio.run(run_worker(application=build_worker_container(settings), settings=settings))


if __name__ == "__main__":
    main()
