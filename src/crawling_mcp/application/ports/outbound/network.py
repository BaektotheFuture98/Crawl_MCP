from __future__ import annotations

from typing import Protocol


class EgressProxyPort(Protocol):
    """Lifecycle and endpoint contract for a policy-enforcing egress proxy."""

    @property
    def url(self) -> str: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...
