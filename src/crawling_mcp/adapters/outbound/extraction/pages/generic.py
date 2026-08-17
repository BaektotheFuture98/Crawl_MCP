from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from crawling_mcp.domain.models import PageItem, PageSnapshot


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
        content = " ".join(soup.get_text(" ", strip=True).split())
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
            )
        ]
