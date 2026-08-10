from datetime import UTC, datetime
from uuid import uuid4

from crawling_mcp.domain.articles import ArticleCandidate, ArticleCrawlState
from crawling_mcp.domain.change_detector import ArticleChangeDetector
from crawling_mcp.domain.enums import ChangeType


def candidate(content: str = "기사 본문") -> ArticleCandidate:
    return ArticleCandidate(
        url="https://example.com/news/1?utm_source=agent#section",
        title="  기사   제목 ",
        content=content,
        reporter="홍길동 기자",
        publisher="동아일보",
        published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def test_missing_state_is_new_and_canonicalized() -> None:
    result = ArticleChangeDetector().detect(None, candidate())

    assert result.change_type is ChangeType.NEW
    assert result.candidate.url == "https://example.com/news/1"
    assert result.candidate.title == "기사 제목"


def test_same_article_fingerprint_is_unchanged() -> None:
    detector = ArticleChangeDetector()
    current = candidate()
    previous = ArticleCrawlState(
        article_id=uuid4(),
        target_id=uuid4(),
        url="https://example.com/news/1",
        content_hash=detector.fingerprint(current),
    )

    assert detector.detect(previous, current).change_type is ChangeType.UNCHANGED


def test_changed_article_field_is_updated() -> None:
    detector = ArticleChangeDetector()
    previous_candidate = candidate()
    previous = ArticleCrawlState(
        article_id=uuid4(),
        target_id=uuid4(),
        url="https://example.com/news/1",
        content_hash=detector.fingerprint(previous_candidate),
    )

    assert (
        detector.detect(previous, candidate("수정된 기사 본문")).change_type is ChangeType.UPDATED
    )
