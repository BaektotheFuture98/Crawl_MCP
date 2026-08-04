from __future__ import annotations


class ApplicationContainer:
    """Owns long-lived application dependencies."""

    async def start(self) -> None:
        """Start long-lived resources."""

    async def close(self) -> None:
        """Close long-lived resources."""
