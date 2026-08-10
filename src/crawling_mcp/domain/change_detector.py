from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from crawling_mcp.domain.articles import ArticleCandidate, ArticleCrawlState
from crawling_mcp.domain.enums import ChangeType
from crawling_mcp.domain.policies import normalize_url


def _text(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").split())


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        return value.isoformat(timespec="seconds")
    return value.astimezone(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class ArticleDetection:
    candidate: ArticleCandidate
    content_hash: str
    change_type: ChangeType


class ArticleChangeDetector:
    """Canonicalize extracted article data and compare its stable fingerprint."""

    def canonicalize(self, candidate: ArticleCandidate) -> ArticleCandidate:
        return candidate.model_copy(
            update={
                "url": normalize_url(candidate.url, remove_tracking=True),
                "title": _text(candidate.title),
                "content": _text(candidate.content),
                "reporter": _text(candidate.reporter) or None,
                "publisher": _text(candidate.publisher) or None,
            }
        )

    def fingerprint(self, candidate: ArticleCandidate) -> str:
        canonical = self.canonicalize(candidate)
        payload = {
            "content": canonical.content,
            "published_at": _timestamp(canonical.published_at),
            "publisher": canonical.publisher or "",
            "reporter": canonical.reporter or "",
            "title": canonical.title,
            "url": canonical.url,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def detect(
        self,
        previous: ArticleCrawlState | None,
        candidate: ArticleCandidate,
    ) -> ArticleDetection:
        canonical = self.canonicalize(candidate)
        content_hash = self.fingerprint(canonical)
        if previous is None:
            change_type = ChangeType.NEW
        elif previous.content_hash == content_hash:
            change_type = ChangeType.UNCHANGED
        else:
            change_type = ChangeType.UPDATED
        return ArticleDetection(canonical, content_hash, change_type)
