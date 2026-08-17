from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from crawling_mcp.adapters.outbound.artifacts import FailureArtifactWriter
from crawling_mcp.domain.errors import AuthenticationFailedError


class FakePage:
    async def content(self) -> str:
        return """<html><body><input name="username" value="reader-name">
        <input name="password" type="password" value="reader-secret"></body></html>"""

    async def screenshot(self, *, path: str, full_page: bool) -> None:
        await asyncio.to_thread(Path(path).write_bytes, b"png")

    def locator(self, selector: str) -> FakePage:
        return self

    async def aria_snapshot(self) -> str:
        return '- textbox "아이디": reader-name\n- textbox "비밀번호": reader-secret'


@pytest.mark.asyncio
async def test_failure_writer_captures_safe_debug_artifacts(tmp_path: Path) -> None:
    writer = FailureArtifactWriter(tmp_path)
    job_id = uuid4()
    error = AuthenticationFailedError(domain="example.com", password="secret")

    paths = await writer.capture(
        job_id,
        error,
        page=FakePage(),
        sensitive_values=("reader-name", "reader-secret"),
    )

    folder = tmp_path / str(job_id)
    assert Path(paths.error_json) == folder / "error.json"
    assert (folder / "page.html").is_file()
    assert (folder / "screenshot.png").read_bytes() == b"png"
    assert (folder / "accessibility_snapshot.txt").is_file()
    assert "secret" not in (folder / "error.json").read_text(encoding="utf-8")
    for name in ("page.html", "accessibility_snapshot.txt"):
        content = (folder / name).read_text(encoding="utf-8")
        assert "reader-name" not in content
        assert "reader-secret" not in content


@pytest.mark.asyncio
async def test_failure_writer_never_replaces_original_error_on_filesystem_failure(
    tmp_path: Path,
) -> None:
    unusable_root = tmp_path / "not-a-directory"
    unusable_root.write_text("occupied", encoding="utf-8")
    writer = FailureArtifactWriter(unusable_root)

    paths = await writer.capture(uuid4(), AuthenticationFailedError(reason="original"))

    assert paths.error_json.endswith("error.json")


@pytest.mark.asyncio
async def test_failure_writer_keeps_concurrent_page_artifacts_distinct(tmp_path: Path) -> None:
    writer = FailureArtifactWriter(tmp_path)
    job_id = uuid4()

    first, second = await asyncio.gather(
        writer.capture(job_id, AuthenticationFailedError(reason="first"), page=FakePage()),
        writer.capture(job_id, AuthenticationFailedError(reason="second"), page=FakePage()),
    )

    assert first.error_json != second.error_json
    assert await asyncio.to_thread(Path(first.error_json).is_file)
    assert await asyncio.to_thread(Path(second.error_json).is_file)
