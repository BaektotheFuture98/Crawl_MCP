from __future__ import annotations

import asyncio
import builtins
from datetime import datetime, timedelta
from types import TracebackType
from uuid import UUID, uuid4

from crawling_mcp.domain.articles import (
    Article,
    ArticleCandidate,
    ArticleChangeSummary,
    ArticleCrawlState,
    ArticleCrawlStateCreate,
)
from crawling_mcp.domain.enums import ChangeType, CrawlJobStatus
from crawling_mcp.domain.monitoring import CrawlRun, CrawlRunCreate, CrawlTarget, CrawlTargetCreate


class _Targets:
    def __init__(self, store: InMemoryMonitoringStore) -> None:
        self._store = store

    async def create(self, value: CrawlTargetCreate) -> CrawlTarget:
        if any(item.url == value.url for item in self._store._targets.values()):
            raise ValueError("target URL already exists")
        target = CrawlTarget(id=uuid4(), **value.model_dump())
        self._store._targets[target.id] = target
        return target.model_copy(deep=True)

    async def get(self, target_id: UUID) -> CrawlTarget | None:
        target = self._store._targets.get(target_id)
        return target.model_copy(deep=True) if target else None

    async def list(
        self, *, enabled: bool | None = None, limit: int = 100
    ) -> builtins.list[CrawlTarget]:
        values = [
            item
            for item in self._store._targets.values()
            if enabled is None or item.enabled is enabled
        ]
        values.sort(key=lambda item: item.created_at)
        return [item.model_copy(deep=True) for item in values[:limit]]

    async def save(self, target: CrawlTarget) -> CrawlTarget:
        self._store._targets[target.id] = target.model_copy(deep=True)
        return target.model_copy(deep=True)

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_owner: str,
        lease_seconds: int,
    ) -> builtins.list[CrawlTarget]:
        due = [item for item in self._store._targets.values() if item.is_due(now)]
        due.sort(key=lambda item: item.next_retry_at or item.next_crawl_at or item.created_at)
        claimed: list[CrawlTarget] = []
        for target in due[:limit]:
            leased = self._lease(target, now, lease_owner, lease_seconds)
            claimed.append(leased.model_copy(deep=True))
        return claimed

    async def claim(
        self,
        target_id: UUID,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        force: bool,
    ) -> CrawlTarget | None:
        target = self._store._targets.get(target_id)
        if target is None:
            raise KeyError(f"unknown crawl target: {target_id}")
        if not target.enabled:
            return None
        if target.lease_expires_at is not None and target.lease_expires_at > now:
            return None
        if not force and not target.is_due(now):
            return None
        return self._lease(target, now, lease_owner, lease_seconds).model_copy(deep=True)

    def _lease(
        self, target: CrawlTarget, now: datetime, lease_owner: str, lease_seconds: int
    ) -> CrawlTarget:
        leased = target.model_copy(
            update={
                "lease_owner": lease_owner,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
            }
        )
        self._store._targets[target.id] = leased
        return leased

    async def renew_lease(
        self,
        target_id: UUID,
        *,
        lease_owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        target = self._store._targets[target_id]
        if (
            target.lease_owner != lease_owner
            or target.lease_expires_at is None
            or target.lease_expires_at <= now
        ):
            return False
        self._store._targets[target_id] = target.model_copy(
            update={
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "updated_at": now,
            }
        )
        return True

    async def mark_succeeded(
        self,
        target_id: UUID,
        *,
        lease_owner: str,
        crawled_at: datetime,
        next_crawl_at: datetime,
    ) -> bool:
        target = self._store._targets[target_id]
        if (
            target.lease_owner != lease_owner
            or target.lease_expires_at is None
            or target.lease_expires_at <= crawled_at
        ):
            return False
        self._store._targets[target_id] = target.model_copy(
            update={
                "last_crawled_at": crawled_at,
                "next_crawl_at": next_crawl_at,
                "failure_count": 0,
                "last_error": None,
                "last_failed_at": None,
                "next_retry_at": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "updated_at": crawled_at,
            }
        )
        return True

    async def mark_failed(
        self,
        target_id: UUID,
        *,
        lease_owner: str,
        failed_at: datetime,
        error: str,
        next_retry_at: datetime,
    ) -> bool:
        target = self._store._targets[target_id]
        if (
            target.lease_owner != lease_owner
            or target.lease_expires_at is None
            or target.lease_expires_at <= failed_at
        ):
            return False
        self._store._targets[target_id] = target.model_copy(
            update={
                "failure_count": target.failure_count + 1,
                "last_error": error,
                "last_failed_at": failed_at,
                "next_retry_at": next_retry_at,
                "lease_owner": None,
                "lease_expires_at": None,
                "updated_at": failed_at,
            }
        )
        return True


class _Articles:
    def __init__(self, store: InMemoryMonitoringStore) -> None:
        self._store = store

    async def find_by_url(self, url: str) -> Article | None:
        article = next((item for item in self._store._articles.values() if item.url == url), None)
        return article.model_copy(deep=True) if article else None

    async def get_by_id(self, article_id: UUID) -> Article | None:
        article = self._store._articles.get(article_id)
        return article.model_copy(deep=True) if article else None

    async def insert_or_get(self, candidate: ArticleCandidate) -> Article:
        existing = next(
            (item for item in self._store._articles.values() if item.url == candidate.url), None
        )
        if existing is not None:
            return existing.model_copy(deep=True)
        article = Article(id=uuid4(), **candidate.model_dump())
        self._store._articles[article.id] = article
        return article.model_copy(deep=True)

    async def update(self, article_id: UUID, candidate: ArticleCandidate) -> Article:
        article = Article(id=article_id, **candidate.model_dump())
        self._store._articles[article_id] = article
        return article.model_copy(deep=True)


class _States:
    def __init__(self, store: InMemoryMonitoringStore) -> None:
        self._store = store

    async def find_by_url(self, target_id: UUID, url: str) -> ArticleCrawlState | None:
        state = next(
            (
                item
                for item in self._store._states.values()
                if item.target_id == target_id and item.url == url
            ),
            None,
        )
        return state.model_copy(deep=True) if state else None

    async def list_by_target(self, target_id: UUID) -> builtins.list[ArticleCrawlState]:
        return [
            item.model_copy(deep=True)
            for item in self._store._states.values()
            if item.target_id == target_id
        ]

    async def create(self, value: ArticleCrawlStateCreate) -> ArticleCrawlState:
        state = ArticleCrawlState.model_validate(value.model_dump())
        self._store._states[(state.target_id, state.article_id)] = state
        return state.model_copy(deep=True)

    async def save(self, state: ArticleCrawlState) -> ArticleCrawlState:
        self._store._states[(state.target_id, state.article_id)] = state.model_copy(deep=True)
        return state.model_copy(deep=True)

    async def recent_changes(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> builtins.list[ArticleChangeSummary]:
        states = [
            item
            for item in self._store._states.values()
            if item.last_change_type in (ChangeType.NEW, ChangeType.UPDATED)
            and item.last_changed_at is not None
            and (target_id is None or item.target_id == target_id)
        ]
        states.sort(key=lambda item: item.last_changed_at or item.first_seen_at, reverse=True)
        return [self._summary(state) for state in states[:limit]]

    def _summary(self, state: ArticleCrawlState) -> ArticleChangeSummary:
        article = self._store._articles[state.article_id]
        return ArticleChangeSummary(
            article_id=state.article_id,
            target_id=state.target_id,
            change_type=state.last_change_type or ChangeType.NEW,
            title=article.title,
            publisher=article.publisher,
            url=state.url,
            published_at=article.published_at,
            last_changed_at=state.last_changed_at or state.first_seen_at,
        )


class _Runs:
    def __init__(self, store: InMemoryMonitoringStore) -> None:
        self._store = store

    async def create(self, value: CrawlRunCreate) -> CrawlRun:
        run = CrawlRun(id=uuid4(), **value.model_dump())
        self._store._runs[run.id] = run
        return run.model_copy(deep=True)

    async def save(self, run: CrawlRun) -> CrawlRun:
        self._store._runs[run.id] = run.model_copy(deep=True)
        return run.model_copy(deep=True)

    async def save_terminal(self, run: CrawlRun) -> bool:
        current = self._store._runs.get(run.id)
        if current is None or current.status is not CrawlJobStatus.RUNNING:
            return False
        self._store._runs[run.id] = run.model_copy(deep=True)
        return True

    async def fail_running(
        self, target_id: UUID, *, completed_at: datetime, error: str
    ) -> int:
        changed = 0
        for run_id, run in list(self._store._runs.items()):
            if run.target_id != target_id or run.status is not CrawlJobStatus.RUNNING:
                continue
            self._store._runs[run_id] = run.model_copy(
                update={
                    "status": CrawlJobStatus.FAILED,
                    "completed_at": completed_at,
                    "error": error,
                }
            )
            changed += 1
        return changed

    async def latest(
        self, *, target_id: UUID | None = None, limit: int = 50
    ) -> builtins.list[CrawlRun]:
        runs = [
            item
            for item in self._store._runs.values()
            if target_id is None or item.target_id == target_id
        ]
        runs.sort(key=lambda item: item.started_at, reverse=True)
        return [item.model_copy(deep=True) for item in runs[:limit]]


class InMemoryMonitoringStore:
    """Concurrency-safe monitoring UoW used by tests and non-worker composition."""

    def __init__(self) -> None:
        self._targets: dict[UUID, CrawlTarget] = {}
        self._articles: dict[UUID, Article] = {}
        self._states: dict[tuple[UUID, UUID], ArticleCrawlState] = {}
        self._runs: dict[UUID, CrawlRun] = {}
        self._lock = asyncio.Lock()
        self.targets = _Targets(self)
        self.articles = _Articles(self)
        self.states = _States(self)
        self.runs = _Runs(self)

    def __call__(self) -> InMemoryMonitoringStore:
        return self

    async def __aenter__(self) -> InMemoryMonitoringStore:
        await self._lock.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._lock.release()

    async def commit(self) -> None:
        return None

    async def close(self) -> None:
        return None
