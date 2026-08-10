from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog

from crawling_mcp.domain.articles import (
    ArticleCrawlState,
    ArticleCrawlStateCreate,
    ArticleObservation,
    ArticlePersistenceResult,
)
from crawling_mcp.domain.change_detector import ArticleChangeDetector
from crawling_mcp.domain.enums import ChangeType
from crawling_mcp.ports.monitoring import MonitoringUnitOfWorkFactory


class ArticlePersistenceService:
    """Atomically keep ARTICLE current and crawler state separate."""

    def __init__(
        self,
        *,
        uow_factory: MonitoringUnitOfWorkFactory,
        detector: ArticleChangeDetector | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._detector = detector or ArticleChangeDetector()
        self._log = structlog.get_logger(__name__)

    async def persist(
        self,
        *,
        target_id: UUID,
        observation: ArticleObservation,
        observed_at: datetime,
    ) -> ArticlePersistenceResult:
        candidate = self._detector.canonicalize(observation.candidate)
        async with self._uow_factory() as uow:
            article = await uow.articles.find_by_url(candidate.url)
            state = await uow.states.find_by_url(candidate.url)
            previous = state
            if article is not None and previous is None:
                previous = ArticleCrawlState(
                    article_id=article.id,
                    target_id=target_id,
                    url=candidate.url,
                    content_hash=self._detector.fingerprint(article.as_candidate()),
                    first_seen_at=observed_at,
                    last_seen_at=observed_at,
                )

            detection = self._detector.detect(previous, candidate)
            if article is None:
                article = await uow.articles.insert(detection.candidate)
                change_type = ChangeType.NEW
            elif detection.change_type is ChangeType.UPDATED:
                article = await uow.articles.update(article.id, detection.candidate)
                change_type = ChangeType.UPDATED
            else:
                change_type = ChangeType.UNCHANGED

            if state is None:
                state = await uow.states.create(
                    ArticleCrawlStateCreate(
                        article_id=article.id,
                        target_id=target_id,
                        url=detection.candidate.url,
                        content_hash=detection.content_hash,
                        etag=observation.etag,
                        last_modified=observation.last_modified,
                        first_seen_at=observed_at,
                        last_seen_at=observed_at,
                        last_changed_at=(
                            observed_at
                            if change_type in (ChangeType.NEW, ChangeType.UPDATED)
                            else None
                        ),
                        last_change_type=(
                            change_type
                            if change_type in (ChangeType.NEW, ChangeType.UPDATED)
                            else None
                        ),
                    )
                )
            else:
                updates: dict[str, object] = {
                    "target_id": target_id,
                    "last_seen_at": observed_at,
                    "etag": observation.etag or state.etag,
                    "last_modified": observation.last_modified or state.last_modified,
                }
                if change_type is ChangeType.UPDATED:
                    updates.update(
                        {
                            "content_hash": detection.content_hash,
                            "last_changed_at": observed_at,
                            "last_change_type": ChangeType.UPDATED,
                        }
                    )
                state = await uow.states.save(state.model_copy(update=updates))
            await uow.commit()

        if change_type is ChangeType.NEW:
            self._log.info(
                "article_created",
                article_id=str(article.id),
                target_id=str(target_id),
                url=article.url,
            )
        elif change_type is ChangeType.UPDATED:
            self._log.info(
                "article_updated",
                article_id=str(article.id),
                target_id=str(target_id),
                url=article.url,
            )
        return ArticlePersistenceResult(
            article_id=article.id,
            url=article.url,
            change_type=change_type,
        )
