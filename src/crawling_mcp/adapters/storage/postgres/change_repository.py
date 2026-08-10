from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from crawling_mcp.adapters.storage.postgres.mapping import change_from_row
from crawling_mcp.adapters.storage.postgres.schema import crawl_changes
from crawling_mcp.adapters.storage.postgres.snapshot_repository import (
    PostgresSnapshotRepository,
)
from crawling_mcp.domain.monitoring import CrawlChange, CrawlChangeCreate, CrawlSnapshot


class PostgresChangeRepository:
    """SQLAlchemy async adapter for compact change events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._snapshots = PostgresSnapshotRepository(session)

    async def create(self, change: CrawlChangeCreate) -> CrawlChange:
        statement = (
            sa.insert(crawl_changes)
            .values(
                target_id=change.target_id,
                change_type=change.change_type.value,
                url=change.url,
                title=change.title,
                previous_snapshot_id=change.previous_snapshot_id,
                current_snapshot_id=change.current_snapshot_id,
                detected_at=change.detected_at,
            )
            .returning(crawl_changes)
        )
        row = (await self._session.execute(statement)).mappings().one()
        return change_from_row(row)

    async def recent(self, *, target_id: UUID | None = None, limit: int = 50) -> list[CrawlChange]:
        statement = (
            sa.select(crawl_changes).order_by(crawl_changes.c.detected_at.desc()).limit(limit)
        )
        if target_id is not None:
            statement = statement.where(crawl_changes.c.target_id == target_id)
        rows = (await self._session.execute(statement)).mappings().all()
        return [change_from_row(row) for row in rows]

    async def detail(self, change_id: UUID) -> tuple[CrawlChange, CrawlSnapshot] | None:
        statement = sa.select(crawl_changes).where(crawl_changes.c.id == change_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        change = change_from_row(row)
        snapshot = await self._snapshots.get(change.current_snapshot_id)
        if snapshot is None:
            return None
        return change, snapshot
