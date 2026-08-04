from __future__ import annotations

from typing import Protocol


class RobotsPolicy(Protocol):
    """Decide whether robots.txt allows fetching a URL."""

    async def allowed(self, url: str) -> bool: ...
