from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from crawling_mcp.domain.articles import ArticleCandidate
from crawling_mcp.domain.models import PageSnapshot
from crawling_mcp.domain.policies import normalize_url

_ARTICLE_TYPES = {"Article", "NewsArticle", "ReportageNewsArticle", "AnalysisNewsArticle"}


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _named(value: object) -> str | None:
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, dict):
        return _text(value.get("name"))
    if isinstance(value, list):
        names = [name for item in value if (name := _named(item))]
        return ", ".join(names) or None
    return None


def _published(value: object) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _json_objects(value: object) -> list[dict[str, Any]]:
    if isinstance(value, list):
        objects: list[dict[str, Any]] = []
        for item in value:
            objects.extend(_json_objects(item))
        return objects
    if not isinstance(value, dict):
        return []
    objects = [value]
    graph = value.get("@graph")
    if graph is not None:
        objects.extend(_json_objects(graph))
    return objects


def _is_article(value: dict[str, Any]) -> bool:
    article_type = value.get("@type")
    if isinstance(article_type, str):
        return article_type in _ARTICLE_TYPES
    if isinstance(article_type, list):
        return any(item in _ARTICLE_TYPES for item in article_type)
    return False


class StructuredArticleExtractor:
    """Extract articles from schema.org, OpenGraph, then semantic HTML."""

    @property
    def name(self) -> str:
        return "structured-article"

    @staticmethod
    def _meta(
        soup: BeautifulSoup, *, property_name: str | None = None, name: str | None = None
    ) -> str | None:
        attrs = {"property": property_name} if property_name else {"name": name}
        tag = soup.find("meta", attrs=attrs)
        return _text(tag.get("content")) if isinstance(tag, Tag) else None

    @staticmethod
    def _json_article(soup: BeautifulSoup) -> dict[str, Any]:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                payload = json.loads(script.get_text())
            except (TypeError, json.JSONDecodeError):
                continue
            for value in _json_objects(payload):
                if _is_article(value):
                    return value
        return {}

    async def extract_articles(self, snapshot: PageSnapshot) -> list[ArticleCandidate]:
        soup = BeautifulSoup(snapshot.html, "lxml")
        structured = self._json_article(soup)
        article = soup.find("article")
        heading = article.find("h1") if isinstance(article, Tag) else None

        title = (
            _text(structured.get("headline"))
            or self._meta(soup, property_name="og:title")
            or (_text(heading.get_text(" ", strip=True)) if isinstance(heading, Tag) else None)
        )
        content = _text(structured.get("articleBody"))
        if content is None and isinstance(article, Tag):
            paragraphs = [
                text
                for node in article.find_all("p")
                if (text := _text(node.get_text(" ", strip=True)))
            ]
            content = "\n".join(paragraphs) or _text(article.get_text(" ", strip=True))
            if title and content and content.startswith(title):
                content = content[len(title) :].strip()

        if not title or not content:
            return []

        canonical_tag = soup.find(
            "link", attrs={"rel": lambda value: value and "canonical" in value}
        )
        canonical = (
            _text(structured.get("url"))
            or self._meta(soup, property_name="og:url")
            or (_text(canonical_tag.get("href")) if isinstance(canonical_tag, Tag) else None)
            or snapshot.url
        )
        reporter = (
            _named(structured.get("author"))
            or self._meta(soup, name="author")
            or (
                _text(node.get_text(" ", strip=True))
                if isinstance(
                    (
                        node := article.find(attrs={"rel": "author"})
                        if isinstance(article, Tag)
                        else None
                    ),
                    Tag,
                )
                else None
            )
        )
        publisher = _named(structured.get("publisher")) or self._meta(
            soup, property_name="og:site_name"
        )
        published_at = _published(structured.get("datePublished")) or _published(
            self._meta(soup, property_name="article:published_time")
        )
        if published_at is None and isinstance(article, Tag):
            time_tag = article.find("time")
            if isinstance(time_tag, Tag):
                published_at = _published(time_tag.get("datetime"))

        return [
            ArticleCandidate(
                url=normalize_url(urljoin(snapshot.url, canonical), remove_tracking=True),
                title=title,
                content=content,
                reporter=reporter[:100] if reporter else None,
                publisher=publisher[:100] if publisher else None,
                published_at=published_at,
            )
        ]
