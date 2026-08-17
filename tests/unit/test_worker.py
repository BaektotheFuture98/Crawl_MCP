from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from crawling_mcp.adapters.inbound.worker.scheduler import MonitoringScheduler


class RecordingMonitoring:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.called = asyncio.Event()

    async def run_due_targets(
        self, *, worker_id: str, batch_size: int, lease_seconds: int
    ) -> list[object]:
        self.calls.append((worker_id, batch_size, lease_seconds))
        self.called.set()
        return []


@pytest.mark.asyncio
async def test_scheduler_run_once_delegates_directly_to_monitoring_service() -> None:
    monitoring = RecordingMonitoring()
    scheduler = MonitoringScheduler(
        monitoring=monitoring,
        worker_id="worker-1",
        poll_interval_seconds=1,
        batch_size=5,
        lease_seconds=60,
    )

    await scheduler.run_once()

    assert monitoring.calls == [("worker-1", 5, 60)]


@pytest.mark.asyncio
async def test_scheduler_stops_gracefully_via_event() -> None:
    monitoring = RecordingMonitoring()
    scheduler = MonitoringScheduler(
        monitoring=monitoring,
        worker_id="worker-1",
        poll_interval_seconds=60,
        batch_size=5,
        lease_seconds=60,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(scheduler.run(stop))
    await monitoring.called.wait()

    stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert len(monitoring.calls) == 1


def test_worker_adapter_does_not_depend_on_mcp_transport() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/crawling_mcp/adapters/worker").glob("*.py")
    )

    assert "adapters.inbound.mcp" not in source
    assert "call_tool" not in source
