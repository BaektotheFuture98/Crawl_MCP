from __future__ import annotations

from uuid import UUID

from crawling_mcp.application.ports.inbound.collection import CollectionRunner
from crawling_mcp.application.ports.outbound.monitoring import MonitoringUnitOfWorkFactory
from crawling_mcp.domain.articles import Article
from crawling_mcp.domain.collection import ArticleDiscoverySummary
from crawling_mcp.domain.models import utc_now
from crawling_mcp.domain.monitoring import (
    CollectionResult,
    ConfigureTargetRequest,
    CrawlRun,
    CrawlTarget,
    CrawlTargetCreate,
)


class CollectionQueryService:
    """Bounded article discovery commands and queries for transport adapters."""

    def __init__(
        self,
        *,
        uow_factory: MonitoringUnitOfWorkFactory,
        monitoring: CollectionRunner,
    ) -> None:
        self._uow_factory = uow_factory
        self._monitoring = monitoring

    async def configure_target(self, request: ConfigureTargetRequest) -> CrawlTarget:
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

    async def run_target(self, target_id: UUID) -> CollectionResult:
        result = await self._monitoring.run_target(target_id, force=True)
        if result is None:
            raise RuntimeError("target is disabled or already leased")
        return result

    async def get_crawl_status(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> list[CrawlRun]:
        async with self._uow_factory() as uow:
            return await uow.runs.latest(
                target_id=target_id,
                limit=min(max(limit, 1), 100),
            )

    async def get_recent_articles(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> list[ArticleDiscoverySummary]:
        async with self._uow_factory() as uow:
            return await uow.discoveries.list_recent(
                target_id=target_id,
                limit=min(max(limit, 1), 100),
            )

    async def get_article(self, article_id: UUID) -> Article | None:
        async with self._uow_factory() as uow:
            return await uow.articles.get_by_id(article_id)
