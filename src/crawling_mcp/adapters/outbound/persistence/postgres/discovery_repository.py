from __future__ import annotations

import builtins
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from crawling_mcp.adapters.outbound.persistence.postgres.mapping import discovery_summary_from_row
from crawling_mcp.adapters.outbound.persistence.postgres.schema import article, article_discovery
from crawling_mcp.domain.collection import ArticleDiscoveryCreate, ArticleDiscoverySummary


class PostgresArticleDiscoveryRepository:
    """Idempotent target/article discovery persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, discovery: ArticleDiscoveryCreate) -> bool:
        inserted = await self._session.execute(
            insert(article_discovery)
            .values(**discovery.model_dump())
            .on_conflict_do_nothing(
                index_elements=[article_discovery.c.target_id, article_discovery.c.article_id]
            )
            .returning(article_discovery.c.article_id)
        )
        return inserted.scalar_one_or_none() is not None

    async def list_recent(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> builtins.list[ArticleDiscoverySummary]:
        statement = (
            sa.select(
                article_discovery,
                article.c.ar_title,
                article.c.publisher,
                article.c.url,
                article.c.published_at,
            )
            .join(article, article.c.id == article_discovery.c.article_id)
            .order_by(article_discovery.c.discovered_at.desc())
            .limit(limit)
        )
        if target_id is not None:
            statement = statement.where(article_discovery.c.target_id == target_id)
        rows = (await self._session.execute(statement)).mappings().all()
        return [discovery_summary_from_row(row) for row in rows]
