from __future__ import annotations

import asyncio
import contextlib
import signal
import socket
from typing import Protocol, cast

from crawling_mcp.adapters.worker.scheduler import DueTargetRunner, MonitoringScheduler
from crawling_mcp.infrastructure.config import Settings


class WorkerApplication(Protocol):
    """Lifecycle and application services owned by one worker process."""

    monitoring_service: DueTargetRunner

    async def start(self) -> None: ...

    async def close(self) -> None: ...


async def run_worker(
    *,
    application: WorkerApplication | None = None,
    settings: Settings | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Start one worker container and run its scheduler until shutdown."""
    configured = settings or Settings()
    resolved = application
    if resolved is None:
        from crawling_mcp.bootstrap import build_worker_container

        resolved = cast(WorkerApplication, build_worker_container(configured))
    stop_event = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    if stop is None:
        for name in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(name, stop_event.set)
    scheduler = MonitoringScheduler(
        monitoring=resolved.monitoring_service,
        worker_id=f"{socket.gethostname()}-{id(resolved):x}",
        poll_interval_seconds=configured.worker_poll_interval_seconds,
        batch_size=configured.worker_batch_size,
        lease_seconds=configured.worker_lease_seconds,
    )
    await resolved.start()
    try:
        await scheduler.run(stop_event)
    finally:
        await resolved.close()
