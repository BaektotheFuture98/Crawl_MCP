from __future__ import annotations

from bs4 import BeautifulSoup

from crawling_mcp.adapters.extractors.generic import GenericExtractor
from crawling_mcp.domain.models import PageItem, PageSnapshot


class ExampleExtractor(GenericExtractor):
    """Extractor for the local authenticated test site."""

    def __init__(self) -> None:
        super().__init__(name="example")

    async def extract(self, snapshot: PageSnapshot) -> list[PageItem]:
        """Extract test-site detail data and retain generic fields."""
        items = await super().extract(snapshot)
        soup = BeautifulSoup(snapshot.html, "lxml")
        product = soup.select_one("[data-testid='detail']")
        if product is not None:
            heading = product.select_one("h1")
            items[0].metadata.update(
                {
                    "type": "detail",
                    "id": product.get("data-id"),
                    "name": heading.get_text(strip=True) if heading is not None else None,
                }
            )
        return items
