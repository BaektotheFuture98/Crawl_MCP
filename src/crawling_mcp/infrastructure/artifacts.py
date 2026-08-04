from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from bs4 import BeautifulSoup

from crawling_mcp.domain.errors import CrawlError
from crawling_mcp.domain.models import ArtifactPaths
from crawling_mcp.infrastructure.logging import mask_sensitive


def _sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for element in soup.select("input"):
        name = str(element.get("name", "")).lower()
        input_type = str(element.get("type", "")).lower()
        if input_type == "password" or any(
            word in name for word in ("password", "secret", "token", "authorization")
        ):
            element["value"] = "***REDACTED***"
    return str(soup)


class FailureArtifactWriter:
    """Persist redacted failure diagnostics without masking the original error."""

    def __init__(self, root: Path) -> None:
        self._root = root

    async def capture(
        self, job_id: UUID, error: CrawlError, *, page: Any | None = None
    ) -> ArtifactPaths:
        """Best-effort capture of JSON, HTML, PNG and accessibility diagnostics."""
        folder = self._root / str(job_id)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        error_path = folder / "error.json"
        safe_error = mask_sensitive(error.to_response(job_id).model_dump(mode="json"))
        await asyncio.to_thread(
            error_path.write_text,
            json.dumps(safe_error, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths = ArtifactPaths(error_json=str(error_path))
        if page is None:
            return paths
        try:
            html_path = folder / "page.html"
            html = _sanitize_html(await page.content())
            await asyncio.to_thread(html_path.write_text, html, encoding="utf-8")
            paths.html = str(html_path)
        except Exception:
            pass
        try:
            screenshot_path = folder / "screenshot.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            paths.screenshot = str(screenshot_path)
        except Exception:
            pass
        try:
            accessibility_path = folder / "accessibility_snapshot.txt"
            snapshot = await page.locator("body").aria_snapshot()
            await asyncio.to_thread(accessibility_path.write_text, snapshot, encoding="utf-8")
            paths.accessibility_snapshot = str(accessibility_path)
        except Exception:
            pass
        return paths
