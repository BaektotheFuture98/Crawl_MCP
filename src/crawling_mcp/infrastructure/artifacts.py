from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog
from bs4 import BeautifulSoup

from crawling_mcp.domain.errors import CrawlError
from crawling_mcp.domain.models import ArtifactPaths
from crawling_mcp.infrastructure.logging import mask_sensitive
from crawling_mcp.ports.object_store import ObjectStore, StoredObject


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


def _reserve_failure_folder(root: Path, job_id: UUID) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    job_folder = root / str(job_id)
    try:
        job_folder.mkdir()
        return job_folder
    except FileExistsError:
        unique_folder = job_folder / f"failure-{uuid4().hex}"
        unique_folder.mkdir(parents=True)
        return unique_folder


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
        paths = ArtifactPaths()
        safe_error = mask_sensitive(error.to_response(job_id).model_dump(mode="json"))
        try:
            folder = await asyncio.to_thread(_reserve_failure_folder, self._root, job_id)
            error_path = folder / "error.json"
            paths.error_json = str(error_path)
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


class MinioFailureArtifactWriter:
    """Persist redacted diagnostics in object storage without masking crawl errors."""

    def __init__(self, objects: ObjectStore) -> None:
        self._objects = objects
        self._log = structlog.get_logger(__name__)

    async def _put(
        self,
        job_id: UUID,
        artifact_id: UUID,
        name: str,
        data: bytes,
        content_type: str,
    ) -> StoredObject | None:
        try:
            return await self._objects.put_artifact(job_id, artifact_id, name, data, content_type)
        except Exception as artifact_error:
            self._log.error(
                "object_artifact_capture_failed",
                job_id=str(job_id),
                artifact_name=name,
                error_type=type(artifact_error).__name__,
            )
            return None

    async def capture(
        self,
        job_id: UUID,
        error: CrawlError,
        *,
        page: Any | None = None,
        sensitive_values: tuple[str, ...] = (),
    ) -> ArtifactPaths:
        """Capture safe object references for error JSON and optional page diagnostics."""
        artifact_id = uuid4()
        safe_error = mask_sensitive(error.to_response(job_id).model_dump(mode="json"))
        error_object = await self._put(
            job_id,
            artifact_id,
            "error.json",
            json.dumps(safe_error, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
        )
        paths = ArtifactPaths(error_json=error_object.uri if error_object is not None else None)
        if page is None:
            return paths

        try:
            html = _sanitize_html(await page.content(), sensitive_values).encode("utf-8")
        except Exception:
            html = None
        html_object = (
            await self._put(
                job_id,
                artifact_id,
                "page.html",
                html,
                "text/html; charset=utf-8",
            )
            if html is not None
            else None
        )
        if html_object is not None:
            paths.html = html_object.uri

        with tempfile.TemporaryDirectory(prefix="crawling-mcp-artifact-") as folder:
            screenshot_path = Path(folder) / "screenshot.png"
            try:
                await page.screenshot(path=str(screenshot_path), full_page=True)
                screenshot = await asyncio.to_thread(screenshot_path.read_bytes)
            except Exception:
                screenshot = None
        if screenshot is not None:
            screenshot_object = await self._put(
                job_id, artifact_id, "screenshot.png", screenshot, "image/png"
            )
            if screenshot_object is not None:
                paths.screenshot = screenshot_object.uri

        try:
            accessibility = _redact_values(
                await page.locator("body").aria_snapshot(), sensitive_values
            ).encode("utf-8")
        except Exception:
            accessibility = None
        if accessibility is not None:
            accessibility_object = await self._put(
                job_id,
                artifact_id,
                "accessibility_snapshot.txt",
                accessibility,
                "text/plain; charset=utf-8",
            )
            if accessibility_object is not None:
                paths.accessibility_snapshot = accessibility_object.uri
        return paths
