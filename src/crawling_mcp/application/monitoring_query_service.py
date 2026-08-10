from __future__ import annotations

from uuid import UUID

from crawling_mcp.domain.models import utc_now
from crawling_mcp.domain.monitoring import (
    ConfigureTargetRequest,
    CrawlChange,
    CrawlChangeDetail,
    CrawlJobSummary,
    CrawlTarget,
    CrawlTargetCreate,
    MonitoringRunResult,
)
from crawling_mcp.ports.monitoring import (
    MonitoringUnitOfWorkFactory,
    TargetRunner,
)


class MonitoringQueryService:
    """Bounded monitoring commands and queries exposed by transport adapters."""

    def __init__(
        self,
        *,
        uow_factory: MonitoringUnitOfWorkFactory,
        monitoring: TargetRunner,
    ) -> None:
        self._uow_factory = uow_factory
        self._monitoring = monitoring

    async def configure_target(self, request: ConfigureTargetRequest) -> CrawlTarget:
        """Create a target or update only explicitly supplied fields."""
        values = request.model_dump(exclude={"target_id"}, exclude_none=True)
        async with self._uow_factory() as uow:
            if request.target_id is None:
                if request.url is None or request.interval_seconds is None:
                    raise ValueError("url and interval_seconds are required for target creation")
                stored = await uow.targets.create(CrawlTargetCreate.model_validate(values))
            else:
                current = await uow.targets.get(request.target_id)
                if current is None:
                    raise KeyError(f"unknown crawl target: {request.target_id}")
                payload = current.model_dump()
                payload.update(values)
                payload["updated_at"] = utc_now()
                stored = await uow.targets.save(CrawlTarget.model_validate(payload))
            await uow.commit()
            return stored

    async def list_targets(
        self, *, enabled: bool | None = None, limit: int = 100
    ) -> list[CrawlTarget]:
        async with self._uow_factory() as uow:
            return await uow.targets.list(enabled=enabled, limit=min(max(limit, 1), 100))

    async def run_target(self, target_id: UUID) -> MonitoringRunResult:
        result = await self._monitoring.run_target(target_id, force=True)
        if result is None:
            raise RuntimeError("target was not executed")
        return result

    async def get_crawl_status(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> list[CrawlJobSummary]:
        bounded = min(max(limit, 1), 100)
        async with self._uow_factory() as uow:
            if target_id is not None:
                latest = await uow.jobs.latest(target_id)
                return [latest] if latest is not None else []
            targets = await uow.targets.list(limit=bounded)
            jobs: list[CrawlJobSummary] = []
            for target in targets:
                latest = await uow.jobs.latest(target.id)
                if latest is not None:
                    jobs.append(latest)
            jobs.sort(key=lambda item: item.started_at, reverse=True)
            return jobs[:bounded]

    async def get_recent_changes(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> list[CrawlChange]:
        async with self._uow_factory() as uow:
            return await uow.changes.recent(
                target_id=target_id,
                limit=min(max(limit, 1), 100),
            )

    async def get_change_detail(self, change_id: UUID) -> CrawlChangeDetail | None:
        async with self._uow_factory() as uow:
            detail = await uow.changes.detail(change_id)
            if detail is None:
                return None
            change, snapshot = detail
            return CrawlChangeDetail(change=change, snapshot=snapshot)
