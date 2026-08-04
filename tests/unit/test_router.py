from __future__ import annotations

from crawling_mcp.adapters.crawlee.router import PageRouter
from crawling_mcp.domain.enums import PageType
from crawling_mcp.domain.models import PageSnapshot


def test_router_classifies_start_list_and_detail_pages() -> None:
    router = PageRouter()

    assert router.classify(PageSnapshot(url="https://example.com", html="")) is PageType.START
    assert (
        router.classify(PageSnapshot(url="https://example.com/products", html="<ul></ul>"))
        is PageType.LIST
    )
    assert (
        router.classify(PageSnapshot(url="https://example.com/product/1", html=""))
        is PageType.DETAIL
    )


def test_router_preserves_explicit_non_default_label() -> None:
    router = PageRouter()
    snapshot = PageSnapshot(url="https://example.com/anything", html="", page_type=PageType.LIST)

    assert router.classify(snapshot) is PageType.LIST
