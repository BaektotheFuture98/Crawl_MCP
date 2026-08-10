from __future__ import annotations

from uuid import uuid4

from crawling_mcp.domain.change_detector import ChangeDetector
from crawling_mcp.domain.enums import ChangeType
from crawling_mcp.domain.models import PageItem
from crawling_mcp.domain.monitoring import CrawlSnapshot


def test_first_collection_is_new() -> None:
    detection = ChangeDetector().detect(
        None,
        PageItem(url="https://example.com/news?utm_source=test", title="Title", content="Body"),
    )

    assert detection.change_type is ChangeType.NEW
    assert len(detection.content_hash) == 64


def test_same_canonical_content_is_unchanged() -> None:
    detector = ChangeDetector()
    first = detector.detect(
        None,
        PageItem(
            url="https://example.com/news",
            title="Ａ title",  # noqa: RUF001 - verifies Unicode NFKC normalization
            content="one\n two",
        ),
    )
    previous = CrawlSnapshot(
        id=uuid4(),
        target_id=uuid4(),
        url="https://example.com/news",
        content_hash=first.content_hash,
        title="old storage title",
    )

    detection = detector.detect(
        previous,
        PageItem(
            url="https://example.com/news?utm_campaign=ignored",
            title="A title",
            content="one   two",
        ),
    )

    assert detection.change_type is ChangeType.UNCHANGED
    assert detection.content_hash == first.content_hash


def test_changed_extracted_content_is_updated() -> None:
    previous = CrawlSnapshot(
        id=uuid4(),
        target_id=uuid4(),
        url="https://example.com/news",
        content_hash="0" * 64,
        title="Title",
    )

    detection = ChangeDetector().detect(
        previous,
        PageItem(url="https://example.com/news", title="Title", content="new body"),
    )

    assert detection.change_type is ChangeType.UPDATED


def test_volatile_metadata_and_collection_time_do_not_change_hash() -> None:
    detector = ChangeDetector()
    first = detector.canonicalize(
        PageItem(
            url="https://example.com/news",
            title="Title",
            content="Body",
            metadata={"request_id": "one"},
        )
    )
    second = detector.canonicalize(
        PageItem(
            url="https://example.com/news",
            title="Title",
            content="Body",
            metadata={"request_id": "two"},
        )
    )

    assert first.content_hash == second.content_hash
