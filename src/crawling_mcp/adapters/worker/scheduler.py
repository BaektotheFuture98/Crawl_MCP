from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol

import structlog


class DueTargetRunner(Protocol):
    """Application surface required by the scheduler adapter."""

    async def run_due_targets(
        self, *, worker_id: str, batch_size: int, lease_seconds: int
    ) -> Sequence[object]: ...


class MonitoringScheduler:
    """Small single-process polling loop with graceful stop semantics."""

    def __init__(
        self,
        *,
        monitoring: DueTargetRunner,
        worker_id: str,
        poll_interval_seconds: float,
        batch_size: int,
        lease_seconds: int,
    ) -> None:
        self._monitoring = monitoring
        self._worker_id = worker_id
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._log = structlog.get_logger(__name__)

    async def run_once(self) -> None:
        """Claim and execute one bounded batch."""
        results = await self._monitoring.run_due_targets(
            worker_id=self._worker_id,
            batch_size=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        self._log.info(
            "worker_poll_completed",
            worker_id=self._worker_id,
            completed_targets=len(results),
        )

    async def run(self, stop: asyncio.Event) -> None:
        """Poll until a signal sets the shared stop event."""
        self._log.info("crawler_worker_started", worker_id=self._worker_id)
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception as error:
                self._log.error(
                    "worker_poll_failed",
                    worker_id=self._worker_id,
                    error_type=type(error).__name__,
                )
            if stop.is_set():
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue
        self._log.info("crawler_worker_stopped", worker_id=self._worker_id)
