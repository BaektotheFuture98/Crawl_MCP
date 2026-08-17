from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from crawling_mcp.domain.monitoring import CollectionResult


class CollectionRunner(Protocol):
    async def run_target(
        self, target_id: UUID, *, force: bool = False
    ) -> CollectionResult | None: ...


class DueTargetRunner(Protocol):
    async def run_due_targets(
        self, *, worker_id: str, batch_size: int, lease_seconds: int
    ) -> Sequence[CollectionResult]: ...
