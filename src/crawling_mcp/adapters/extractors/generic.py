from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from crawling_mcp.domain.models import PageItem, PageSnapshot


def _json_ld_nodes(value: Any) -> list[dict[str, Any]]:
    """Flatten JSON-LD objects and graph members into metadata candidates."""
    if isinstance(value, list):
        return [node for item in value for node in _json_ld_nodes(item)]
    if not isinstance(value, dict):
        return []
    nodes = [value]
    graph = value.get("@graph")
    if isinstance(graph, list):
        nodes.extend(node for item in graph for node in _json_ld_nodes(item))
    return nodes


def _article_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Return NewsArticle/Article JSON-LD nodes in document order."""
    candidates: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            document = json.loads(script.get_text())
        except json.JSONDecodeError:
            continue
        for node in _json_ld_nodes(document):
            type_value = node.get("@type")
            types = type_value if isinstance(type_value, list) else [type_value]
            if any(value in {"Article", "NewsArticle", "ReportageNewsArticle"} for value in types):
                candidates.append(node)
    return candidates


def _parse_published_at(value: str | None) -> datetime | None:
    """Parse an ISO article timestamp into a timezone-aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _meta_content(soup: BeautifulSoup, attribute: str, value: str) -> str | None:
    tag = soup.find("meta", attrs={attribute: value})
    if isinstance(tag, Tag) and tag.get("content"):
        return str(tag.get("content")).strip() or None
    return None


def _article_metadata(soup: BeautifulSoup) -> tuple[datetime | None, str | None]:
    """Read publication date and publisher from standard article metadata."""
    nodes = _article_json_ld(soup)
    published = next(
        (
            parsed
            for node in nodes
            if (parsed := _parse_published_at(str(node.get("datePublished", "")))) is not None
        ),
        None,
    )
    if published is None:
        published = _parse_published_at(_meta_content(soup, "property", "article:published_time"))
    if published is None:
        time_tag = soup.find("time")
        if isinstance(time_tag, Tag):
            published = _parse_published_at(str(time_tag.get("datetime", "")))

    source: str | None = None
    for node in nodes:
        publisher = node.get("publisher")
        if isinstance(publisher, dict) and isinstance(publisher.get("name"), str):
            source = publisher["name"].strip() or None
            if source:
                break
    if source is None:
        source = _meta_content(soup, "property", "og:site_name")
    return published, source


class GenericExtractor:
    """Extract readable metadata and body text from ordinary HTML."""

    def __init__(self, name: str = "generic") -> None:
        self._name = name

    @property
    def name(self) -> str:
        """Return public extractor metadata name."""
        return self._name

    async def extract(self, snapshot: PageSnapshot) -> list[PageItem]:
        """Extract a single generic page item."""
        soup = BeautifulSoup(snapshot.html, "lxml")
        published_at, source = _article_metadata(soup)
        for tag in soup.select("script, style, noscript, nav, footer"):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        description_tag = soup.find("meta", attrs={"name": "description"})
        description = (
            str(description_tag.get("content"))
            if isinstance(description_tag, Tag) and description_tag.get("content")
            else None
        )
        canonical_tag = soup.find(
            "link", attrs={"rel": lambda value: value and "canonical" in value}
        )
        canonical = (
            urljoin(snapshot.url, str(canonical_tag.get("href")))
            if isinstance(canonical_tag, Tag) and canonical_tag.get("href")
            else None
        )
        language = str(soup.html.get("lang")) if soup.html and soup.html.get("lang") else None
        content_root = soup.select_one("article") or soup.select_one("main") or soup.body or soup
        content = " ".join(content_root.get_text(" ", strip=True).split())
        if title and content.startswith(title):
            content = content[len(title) :].strip()
        return [
            PageItem(
                url=snapshot.url,
                title=title,
                content=content,
                meta_description=description,
                canonical_url=canonical,
                language=language,
                http_status_code=snapshot.status_code,
                published_at=published_at,
                source=source,
            )
        ]
