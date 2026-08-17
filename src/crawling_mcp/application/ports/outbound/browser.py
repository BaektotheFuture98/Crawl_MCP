from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, Protocol


class BrowserManagerPort(Protocol):
    """Shared browser process and isolated-context port."""

    async def start(self) -> None: ...

    def context(self, storage_state: Path | None = None) -> AbstractAsyncContextManager[Any]: ...

    async def close(self) -> None: ...
