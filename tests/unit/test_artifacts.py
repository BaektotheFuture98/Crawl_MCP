from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from crawling_mcp.domain.errors import AuthenticationFailedError
from crawling_mcp.infrastructure.artifacts import FailureArtifactWriter


class FakePage:
    async def content(self) -> str:
        return "<html><body>failure without secret</body></html>"

    async def screenshot(self, *, path: str, full_page: bool) -> None:
        await asyncio.to_thread(Path(path).write_bytes, b"png")

    def locator(self, selector: str) -> FakePage:
        return self

    async def aria_snapshot(self) -> str:
        return "- document: failure"


@pytest.mark.asyncio
async def test_failure_writer_captures_safe_debug_artifacts(tmp_path: Path) -> None:
    writer = FailureArtifactWriter(tmp_path)
    job_id = uuid4()
    error = AuthenticationFailedError(domain="example.com", password="secret")

    paths = await writer.capture(job_id, error, page=FakePage())

    folder = tmp_path / str(job_id)
    assert Path(paths.error_json) == folder / "error.json"
    assert (folder / "page.html").is_file()
    assert (folder / "screenshot.png").read_bytes() == b"png"
    assert (folder / "accessibility_snapshot.txt").is_file()
    assert "secret" not in (folder / "error.json").read_text(encoding="utf-8")
