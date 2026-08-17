from __future__ import annotations

import asyncio
import contextlib
import signal
import socket
from typing import Protocol

from crawling_mcp.adapters.inbound.worker.scheduler import MonitoringScheduler
from crawling_mcp.application.ports.inbound.collection import DueTargetRunner
from crawling_mcp.bootstrap.config import Settings


class WorkerApplication(Protocol):
    """Lifecycle and application services owned by one worker process."""

    collection_service: DueTargetRunner

    async def start(self) -> None: ...

    async def close(self) -> None: ...


async def run_worker(
    *,
    application: WorkerApplication,
    settings: Settings | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Start one worker container and run its scheduler until shutdown."""
    configured = settings or Settings()
    stop_event = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    if stop is None:
        for name in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(name, stop_event.set)
    scheduler = MonitoringScheduler(
        monitoring=application.collection_service,
        worker_id=f"{socket.gethostname()}-{id(application):x}",
        poll_interval_seconds=configured.worker_poll_interval_seconds,
        batch_size=configured.worker_batch_size,
        lease_seconds=configured.worker_lease_seconds,
    )
    await application.start()
    try:
        await scheduler.run(stop_event)
    finally:
        await application.close()
