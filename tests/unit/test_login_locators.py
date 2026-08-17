from __future__ import annotations

import pytest

from crawling_mcp.adapters.outbound.authentication.example_login import choose_usable_locator
from crawling_mcp.domain.errors import AuthenticationFailedError


class FakeLocator:
    def __init__(self, *, count: int = 1, visible: bool = True, enabled: bool = True) -> None:
        self._count = count
        self._visible = visible
        self._enabled = enabled

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible

    async def is_enabled(self) -> bool:
        return self._enabled


@pytest.mark.asyncio
async def test_locator_selection_uses_first_unique_visible_enabled_candidate() -> None:
    hidden = FakeLocator(visible=False)
    ambiguous = FakeLocator(count=2)
    usable = FakeLocator()

    selected = await choose_usable_locator([hidden, ambiguous, usable], field="username")

    assert selected is usable


@pytest.mark.asyncio
async def test_locator_selection_fails_when_no_candidate_is_usable() -> None:
    with pytest.raises(AuthenticationFailedError) as error:
        await choose_usable_locator([FakeLocator(count=0)], field="password")

    assert error.value.details == {"field": "password", "reason": "locator_not_found"}
