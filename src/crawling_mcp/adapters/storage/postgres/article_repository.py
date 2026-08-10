from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from crawling_mcp.adapters.storage.postgres.mapping import article_from_row, to_article_timestamp
from crawling_mcp.adapters.storage.postgres.schema import article
from crawling_mcp.domain.articles import Article, ArticleCandidate


def _values(candidate: ArticleCandidate) -> dict[str, object]:
    return {
        "ar_title": candidate.title,
        "ar_content": candidate.content,
        "reporter": candidate.reporter,
        "publisher": candidate.publisher,
        "url": candidate.url,
        "published_at": to_article_timestamp(candidate.published_at),
    }


class PostgresArticleRepository:
    """Async adapter for the existing final ARTICLE table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_url(self, url: str) -> Article | None:
        row = (
            (await self._session.execute(sa.select(article).where(article.c.url == url)))
            .mappings()
            .one_or_none()
        )
        return article_from_row(row) if row is not None else None

    async def get_by_id(self, article_id: UUID) -> Article | None:
        row = (
            (await self._session.execute(sa.select(article).where(article.c.id == article_id)))
            .mappings()
            .one_or_none()
        )
        return article_from_row(row) if row is not None else None

    async def insert(self, candidate: ArticleCandidate) -> Article:
        row = (
            (
                await self._session.execute(
                    sa.insert(article).values(**_values(candidate)).returning(article)
                )
            )
            .mappings()
            .one()
        )
        return article_from_row(row)

    async def update(self, article_id: UUID, candidate: ArticleCandidate) -> Article:
        row = (
            (
                await self._session.execute(
                    sa.update(article)
                    .where(article.c.id == article_id)
                    .values(**_values(candidate))
                    .returning(article)
                )
            )
            .mappings()
            .one()
        )
        return article_from_row(row)
