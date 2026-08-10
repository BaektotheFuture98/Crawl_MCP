from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from crawling_mcp.adapters.storage.postgres.mapping import snapshot_from_row
from crawling_mcp.adapters.storage.postgres.schema import article, crawl_snapshots
from crawling_mcp.domain.monitoring import CrawlSnapshot, CrawlSnapshotCreate


def _snapshot_select() -> sa.Select[tuple[object, ...]]:
    return sa.select(
        crawl_snapshots,
        article.c.title,
        article.c.content,
        article.c.source,
    ).join(article, article.c.id == crawl_snapshots.c.article_id)


class PostgresSnapshotRepository:
    """SQLAlchemy async adapter for deduplicated content versions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, snapshot: CrawlSnapshotCreate) -> CrawlSnapshot:
        article_statement = (
            insert(article)
            .values(
                collected_at=snapshot.collected_at,
                published_at=snapshot.published_at,
                title=snapshot.title,
                content=snapshot.content,
                source=snapshot.source,
                url=snapshot.url,
                content_hash=snapshot.content_hash,
            )
            .on_conflict_do_update(
                constraint="uq_article_url_content_hash",
                set_={"collected_at": article.c.collected_at},
            )
            .returning(article.c.id)
        )
        article_id = (await self._session.execute(article_statement)).scalar_one()
        snapshot_statement = (
            insert(crawl_snapshots)
            .values(
                target_id=snapshot.target_id,
                article_id=article_id,
                url=snapshot.url,
                content_hash=snapshot.content_hash,
                etag=snapshot.etag,
                last_modified=snapshot.last_modified,
                metadata=snapshot.metadata,
                depth=snapshot.depth,
                collected_at=snapshot.collected_at,
                last_seen_at=snapshot.collected_at,
            )
            .on_conflict_do_update(
                constraint="uq_snapshot_version",
                set_={
                    "last_seen_at": snapshot.collected_at,
                    "etag": snapshot.etag,
                    "last_modified": snapshot.last_modified,
                },
            )
            .returning(crawl_snapshots.c.id)
        )
        snapshot_id = (await self._session.execute(snapshot_statement)).scalar_one()
        stored = await self.get(snapshot_id)
        if stored is None:
            raise RuntimeError("snapshot insert did not return a persisted row")
        return stored

    async def get(self, snapshot_id: UUID) -> CrawlSnapshot | None:
        statement = _snapshot_select().where(crawl_snapshots.c.id == snapshot_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return snapshot_from_row(row) if row is not None else None

    async def latest_by_target(self, target_id: UUID) -> dict[str, CrawlSnapshot]:
        rank = sa.func.row_number().over(
            partition_by=crawl_snapshots.c.url,
            order_by=crawl_snapshots.c.collected_at.desc(),
        )
        ranked = (
            sa.select(crawl_snapshots, rank.label("position"))
            .where(crawl_snapshots.c.target_id == target_id)
            .subquery()
        )
        statement = (
            sa.select(
                *(ranked.c[column.name] for column in crawl_snapshots.c),
                article.c.title,
                article.c.content,
                article.c.source,
            )
            .join(article, article.c.id == ranked.c.article_id)
            .where(ranked.c.position == 1)
        )
        rows = (await self._session.execute(statement)).mappings().all()
        snapshots = [snapshot_from_row(row) for row in rows]
        return {snapshot.url: snapshot for snapshot in snapshots}

    async def list_versions(self, target_id: UUID, url: str) -> list[CrawlSnapshot]:
        statement = (
            _snapshot_select()
            .where(crawl_snapshots.c.target_id == target_id, crawl_snapshots.c.url == url)
            .order_by(crawl_snapshots.c.collected_at)
        )
        rows = (await self._session.execute(statement)).mappings().all()
        return [snapshot_from_row(row) for row in rows]

    async def touch(
        self,
        snapshot_id: UUID,
        *,
        seen_at: datetime,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        values: dict[str, object] = {"last_seen_at": seen_at}
        if etag is not None:
            values["etag"] = etag
        if last_modified is not None:
            values["last_modified"] = last_modified
        await self._session.execute(
            sa.update(crawl_snapshots).where(crawl_snapshots.c.id == snapshot_id).values(**values)
        )
