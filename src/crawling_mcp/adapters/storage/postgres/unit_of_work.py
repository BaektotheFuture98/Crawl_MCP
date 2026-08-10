from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from crawling_mcp.adapters.storage.postgres.change_repository import (
    PostgresChangeRepository,
)
from crawling_mcp.adapters.storage.postgres.job_repository import (
    PostgresMonitoringJobRepository,
)
from crawling_mcp.adapters.storage.postgres.snapshot_repository import (
    PostgresSnapshotRepository,
)
from crawling_mcp.adapters.storage.postgres.target_repository import (
    PostgresTargetRepository,
)
from crawling_mcp.ports.monitoring import (
    ChangeRepository,
    MonitoringJobRepository,
    SnapshotRepository,
    TargetRepository,
)


class PostgresMonitoringUnitOfWork:
    """One async SQLAlchemy transaction spanning monitoring repositories."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._session: AsyncSession | None = None
        self.targets: TargetRepository
        self.snapshots: SnapshotRepository
        self.changes: ChangeRepository
        self.jobs: MonitoringJobRepository

    async def __aenter__(self) -> PostgresMonitoringUnitOfWork:
        session = self._sessions()
        self._session = session
        self.targets = PostgresTargetRepository(session)
        self.snapshots = PostgresSnapshotRepository(session)
        self.changes = PostgresChangeRepository(session)
        self.jobs = PostgresMonitoringJobRepository(session)
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
    """Unit-of-work factory and lifecycle owner for monitoring persistence."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    def __call__(self) -> PostgresMonitoringUnitOfWork:
        return PostgresMonitoringUnitOfWork(self._sessions)

    async def close(self) -> None:
        await self._engine.dispose()
