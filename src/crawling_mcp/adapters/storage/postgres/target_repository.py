from __future__ import annotations

import builtins
from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from crawling_mcp.adapters.storage.postgres.mapping import target_from_row
from crawling_mcp.adapters.storage.postgres.schema import crawl_target
from crawling_mcp.domain.monitoring import CrawlTarget, CrawlTargetCreate


def _options(value: CrawlTarget | CrawlTargetCreate) -> dict[str, object]:
    names = (
        "max_pages",
        "max_depth",
        "include_patterns",
        "exclude_patterns",
        "same_domain_only",
        "max_request_retries",
        "request_timeout_seconds",
        "job_timeout_seconds",
        "max_concurrency",
        "respect_robots_txt",
        "request_delay_seconds",
        "remove_tracking_parameters",
    )
    return {name: getattr(value, name) for name in names}


class PostgresTargetRepository:
    """SQLAlchemy async adapter for targets, schedules, retries, and leases."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, target: CrawlTargetCreate) -> CrawlTarget:
        statement = (
            sa.insert(crawl_target)
            .values(
                url=target.url,
                interval_seconds=target.interval_seconds,
                enabled=target.enabled,
                crawl_mode=target.crawl_mode.value,
                auth_profile=target.auth_profile,
                crawl_options=_options(target),
            )
            .returning(crawl_target)
        )
        row = (await self._session.execute(statement)).mappings().one()
        return target_from_row(row)

    async def get(self, target_id: UUID) -> CrawlTarget | None:
        statement = sa.select(crawl_target).where(crawl_target.c.id == target_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return target_from_row(row) if row is not None else None

    async def list(
        self, *, enabled: bool | None = None, limit: int = 100
    ) -> builtins.list[CrawlTarget]:
        statement = sa.select(crawl_target).order_by(crawl_target.c.created_at).limit(limit)
        if enabled is not None:
            statement = statement.where(crawl_target.c.enabled.is_(enabled))
        rows = (await self._session.execute(statement)).mappings().all()
        return [target_from_row(row) for row in rows]

    async def save(self, target: CrawlTarget) -> CrawlTarget:
        statement = (
            sa.update(crawl_target)
            .where(crawl_target.c.id == target.id)
            .values(
                url=target.url,
                interval_seconds=target.interval_seconds,
                enabled=target.enabled,
                crawl_mode=target.crawl_mode.value,
                auth_profile=target.auth_profile,
                crawl_options=_options(target),
                updated_at=target.updated_at,
                next_crawl_at=target.next_crawl_at,
            )
            .returning(crawl_target)
        )
        row = (await self._session.execute(statement)).mappings().one()
        return target_from_row(row)

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_owner: str,
        lease_seconds: int,
    ) -> builtins.list[CrawlTarget]:
        due_at = sa.case(
            (crawl_target.c.next_retry_at.is_not(None), crawl_target.c.next_retry_at),
            else_=crawl_target.c.next_crawl_at,
        )
        statement = (
            sa.select(crawl_target.c.id)
            .where(
                crawl_target.c.enabled.is_(True),
                sa.or_(
                    crawl_target.c.lease_expires_at.is_(None),
                    crawl_target.c.lease_expires_at <= now,
                ),
                sa.or_(due_at.is_(None), due_at <= now),
            )
            .order_by(due_at.asc().nullsfirst(), crawl_target.c.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ids = list((await self._session.execute(statement)).scalars())
        if not ids:
            return []
        update = (
            sa.update(crawl_target)
            .where(crawl_target.c.id.in_(ids))
            .values(
                lease_owner=lease_owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
            .returning(crawl_target)
        )
        rows = (await self._session.execute(update)).mappings().all()
        by_id = {row["id"]: target_from_row(row) for row in rows}
        return [by_id[target_id] for target_id in ids]

    async def claim(
        self,
        target_id: UUID,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        force: bool,
    ) -> CrawlTarget | None:
        due_at = sa.case(
            (crawl_target.c.next_retry_at.is_not(None), crawl_target.c.next_retry_at),
            else_=crawl_target.c.next_crawl_at,
        )
        conditions = [
            crawl_target.c.id == target_id,
            crawl_target.c.enabled.is_(True),
            sa.or_(
                crawl_target.c.lease_expires_at.is_(None),
                crawl_target.c.lease_expires_at <= now,
            ),
        ]
        if not force:
            conditions.append(sa.or_(due_at.is_(None), due_at <= now))
        selected = (
            await self._session.execute(
                sa.select(crawl_target.c.id).where(*conditions).with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if selected is None:
            exists = (
                await self._session.execute(
                    sa.select(crawl_target.c.id).where(crawl_target.c.id == target_id)
                )
            ).scalar_one_or_none()
            if exists is None:
                raise KeyError(f"unknown crawl target: {target_id}")
            return None
        row = (
            (
                await self._session.execute(
                    sa.update(crawl_target)
                    .where(crawl_target.c.id == target_id)
                    .values(
                        lease_owner=lease_owner,
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                        updated_at=now,
                    )
                    .returning(crawl_target)
                )
            )
            .mappings()
            .one()
        )
        return target_from_row(row)

    async def mark_succeeded(
        self,
        target_id: UUID,
        *,
        lease_owner: str,
        crawled_at: datetime,
        next_crawl_at: datetime,
    ) -> bool:
        updated = await self._session.execute(
            sa.update(crawl_target)
            .where(
                crawl_target.c.id == target_id,
                crawl_target.c.lease_owner == lease_owner,
                crawl_target.c.lease_expires_at > crawled_at,
            )
            .values(
                last_crawled_at=crawled_at,
                next_crawl_at=next_crawl_at,
                failure_count=0,
                last_error=None,
                next_retry_at=None,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=crawled_at,
            )
            .returning(crawl_target.c.id)
        )
        return updated.scalar_one_or_none() is not None

    async def renew_lease(
        self,
        target_id: UUID,
        *,
        lease_owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        updated = await self._session.execute(
            sa.update(crawl_target)
            .where(
                crawl_target.c.id == target_id,
                crawl_target.c.lease_owner == lease_owner,
                crawl_target.c.lease_expires_at > now,
            )
            .values(
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
            .returning(crawl_target.c.id)
        )
        return updated.scalar_one_or_none() is not None

    async def mark_failed(
        self,
        target_id: UUID,
        *,
        lease_owner: str,
        failed_at: datetime,
        error: str,
        next_retry_at: datetime,
    ) -> bool:
        updated = await self._session.execute(
            sa.update(crawl_target)
            .where(
                crawl_target.c.id == target_id,
                crawl_target.c.lease_owner == lease_owner,
                crawl_target.c.lease_expires_at > failed_at,
            )
            .values(
                failure_count=crawl_target.c.failure_count + 1,
                last_error=error,
                last_failed_at=failed_at,
                next_retry_at=next_retry_at,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=failed_at,
            )
            .returning(crawl_target.c.id)
        )
        return updated.scalar_one_or_none() is not None
