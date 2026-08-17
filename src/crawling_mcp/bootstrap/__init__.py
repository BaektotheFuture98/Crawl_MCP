from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from crawling_mcp.bootstrap.composition import ApplicationContainer

__all__ = ["ApplicationContainer", "build_container", "build_worker_container"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    from crawling_mcp.bootstrap import composition

    return getattr(composition, name)
