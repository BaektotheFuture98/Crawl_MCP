from __future__ import annotations

from urllib.parse import urlsplit

from crawling_mcp.domain.enums import PageType
from crawling_mcp.domain.models import PageSnapshot


class PageRouter:
    """Classify pages into stable Crawlee Router labels."""

    def classify(self, snapshot: PageSnapshot) -> PageType:
        """Return an explicit label or use conservative URL heuristics."""
        if snapshot.page_type is not PageType.DETAIL:
            return snapshot.page_type
        path = urlsplit(snapshot.url).path.rstrip("/")
        if path in {"", "/"}:
            return PageType.START
        lowered = path.lower()
        if any(part in lowered for part in ("/list", "/products", "/search", "/category")):
            return PageType.LIST
        return PageType.DETAIL
