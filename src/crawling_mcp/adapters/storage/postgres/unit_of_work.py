from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from crawling_mcp.adapters.storage.postgres.article_repository import PostgresArticleRepository
from crawling_mcp.adapters.storage.postgres.run_repository import PostgresCrawlRunRepository
from crawling_mcp.adapters.storage.postgres.state_repository import (
    PostgresArticleCrawlStateRepository,
)
from crawling_mcp.adapters.storage.postgres.target_repository import PostgresTargetRepository
from crawling_mcp.ports.monitoring import (
    ArticleCrawlStateRepository,
    ArticleRepository,
    CrawlRunRepository,
    TargetRepository,
)


class PostgresMonitoringUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._session: AsyncSession | None = None
        self.targets: TargetRepository
        self.articles: ArticleRepository
        self.states: ArticleCrawlStateRepository
        self.runs: CrawlRunRepository

    async def __aenter__(self) -> PostgresMonitoringUnitOfWork:
        self._session = self._sessions()
        self.targets = PostgresTargetRepository(self._session)
        self.articles = PostgresArticleRepository(self._session)
        self.states = PostgresArticleCrawlStateRepository(self._session)
        self.runs = PostgresCrawlRunRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        if exc_type is not None:
            await self._session.rollback()
        await self._session.close()
        self._session = None

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        await self._session.commit()


class PostgresMonitoringStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    def __call__(self) -> PostgresMonitoringUnitOfWork:
        return PostgresMonitoringUnitOfWork(self._sessions)

    async def close(self) -> None:
        await self._engine.dispose()
