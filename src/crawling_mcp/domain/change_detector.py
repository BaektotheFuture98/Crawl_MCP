from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass

from crawling_mcp.domain.enums import ChangeType
from crawling_mcp.domain.models import PageItem
from crawling_mcp.domain.monitoring import CrawlSnapshot
from crawling_mcp.domain.policies import normalize_url


def _canonical_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


@dataclass(frozen=True, slots=True)
class CanonicalContent:
    """Stable content identity independent of collection-time noise."""

    url: str
    title: str
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class ChangeDetection:
    """Pure comparison result consumed by MonitoringService."""

    change_type: ChangeType
    content_hash: str
    canonical: CanonicalContent


class ChangeDetector:
    """Hash normalized extracted content rather than volatile raw HTML."""

    def canonicalize(self, item: PageItem) -> CanonicalContent:
        url = normalize_url(item.canonical_url or item.url, remove_tracking=True)
        title = _canonical_text(item.title)
        content = _canonical_text(item.content)
        encoded = json.dumps(
            {"url": url, "title": title, "content": content},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return CanonicalContent(
            url=url,
            title=title,
            content=content,
            content_hash=hashlib.sha256(encoded).hexdigest(),
        )

    def detect(self, previous: CrawlSnapshot | None, item: PageItem) -> ChangeDetection:
        canonical = self.canonicalize(item)
        if previous is None:
            change_type = ChangeType.NEW
        elif previous.content_hash == canonical.content_hash:
            change_type = ChangeType.UNCHANGED
        else:
            change_type = ChangeType.UPDATED
        return ChangeDetection(
            change_type=change_type,
            content_hash=canonical.content_hash,
            canonical=canonical,
        )
