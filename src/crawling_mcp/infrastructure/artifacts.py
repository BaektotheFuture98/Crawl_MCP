from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog
from bs4 import BeautifulSoup

from crawling_mcp.domain.errors import CrawlError
from crawling_mcp.domain.models import ArtifactPaths
from crawling_mcp.infrastructure.logging import mask_sensitive


def _redact_values(text: str, sensitive_values: tuple[str, ...]) -> str:
    for value in sensitive_values:
        if value:
            text = text.replace(value, "***REDACTED***")
    return text


def _sanitize_html(html: str, sensitive_values: tuple[str, ...]) -> str:
    soup = BeautifulSoup(html, "lxml")
    for element in soup.select("input"):
        name = str(element.get("name", "")).lower()
        input_type = str(element.get("type", "")).lower()
        if input_type == "password" or any(
            word in name for word in ("password", "secret", "token", "authorization")
        ):
            element["value"] = "***REDACTED***"
    return _redact_values(str(soup), sensitive_values)


def _write_atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class FailureArtifactWriter:
    """Persist redacted failure diagnostics without masking the original error."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._log = structlog.get_logger(__name__)

    async def capture(
        self,
        job_id: UUID,
        error: CrawlError,
        *,
        page: Any | None = None,
        sensitive_values: tuple[str, ...] = (),
    ) -> ArtifactPaths:
        """Best-effort capture of JSON, HTML, PNG and accessibility diagnostics."""
        folder = self._root / str(job_id)
        error_path = folder / "error.json"
        paths = ArtifactPaths(error_json=str(error_path))
        safe_error = mask_sensitive(error.to_response(job_id).model_dump(mode="json"))
        try:
            await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(
                _write_atomic_text,
                error_path,
                json.dumps(safe_error, ensure_ascii=False, indent=2),
            )
        except Exception as artifact_error:
            self._log.error(
                "error_artifact_capture_failed",
                job_id=str(job_id),
                error_type=type(artifact_error).__name__,
            )
            return paths
        if page is None:
            return paths
        try:
            html_path = folder / "page.html"
            html = _sanitize_html(await page.content(), sensitive_values)
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
            snapshot = _redact_values(await page.locator("body").aria_snapshot(), sensitive_values)
            await asyncio.to_thread(accessibility_path.write_text, snapshot, encoding="utf-8")
            paths.accessibility_snapshot = str(accessibility_path)
        except Exception:
            pass
        return paths
