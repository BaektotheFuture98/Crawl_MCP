from __future__ import annotations

import builtins
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from crawling_mcp.adapters.storage.postgres.mapping import (
    change_summary_from_row,
    state_from_row,
)
from crawling_mcp.adapters.storage.postgres.schema import article, article_crawl_state
from crawling_mcp.domain.articles import (
    ArticleChangeSummary,
    ArticleCrawlState,
    ArticleCrawlStateCreate,
)
from crawling_mcp.domain.enums import ChangeType


class PostgresArticleCrawlStateRepository:
    """Async adapter for validators and latest meaningful article state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_url(self, target_id: UUID, url: str) -> ArticleCrawlState | None:
        row = (
            (
                await self._session.execute(
                    sa.select(article_crawl_state).where(
                        article_crawl_state.c.target_id == target_id,
                        article_crawl_state.c.url == url,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return state_from_row(row) if row is not None else None

    async def list_by_target(self, target_id: UUID) -> builtins.list[ArticleCrawlState]:
        rows = (
            (
                await self._session.execute(
                    sa.select(article_crawl_state).where(
                        article_crawl_state.c.target_id == target_id
                    )
                )
            )
            .mappings()
            .all()
        )
        return [state_from_row(row) for row in rows]

    async def create(self, state: ArticleCrawlStateCreate) -> ArticleCrawlState:
        values = state.model_dump()
        values["last_change_type"] = (
            state.last_change_type.value if state.last_change_type else None
        )
        row = (
            (
                await self._session.execute(
                    sa.insert(article_crawl_state).values(**values).returning(article_crawl_state)
                )
            )
            .mappings()
            .one()
        )
        return state_from_row(row)

    async def save(self, state: ArticleCrawlState) -> ArticleCrawlState:
        values = state.model_dump(exclude={"article_id"})
        values["last_change_type"] = (
            state.last_change_type.value if state.last_change_type else None
        )
        row = (
            (
                await self._session.execute(
                    sa.update(article_crawl_state)
                    .where(
                        article_crawl_state.c.target_id == state.target_id,
                        article_crawl_state.c.article_id == state.article_id,
                    )
                    .values(**values)
                    .returning(article_crawl_state)
                )
            )
            .mappings()
            .one()
        )
        return state_from_row(row)

    async def recent_changes(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> builtins.list[ArticleChangeSummary]:
        statement = (
            sa.select(
                article_crawl_state,
                article.c.ar_title,
                article.c.publisher,
                article.c.published_at,
            )
            .join(article, article.c.id == article_crawl_state.c.article_id)
            .where(
                article_crawl_state.c.last_change_type.in_(
                    [ChangeType.NEW.value, ChangeType.UPDATED.value]
                ),
                article_crawl_state.c.last_changed_at.is_not(None),
            )
            .order_by(article_crawl_state.c.last_changed_at.desc())
            .limit(limit)
        )
        if target_id is not None:
            statement = statement.where(article_crawl_state.c.target_id == target_id)
        rows = (await self._session.execute(statement)).mappings().all()
        return [change_summary_from_row(row) for row in rows]
