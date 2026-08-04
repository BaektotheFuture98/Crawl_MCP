from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, Sequence
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import structlog
from structlog.typing import EventDict, WrappedLogger

_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "password",
    "passwd",
    "secret",
    "storage_state",
    "token",
}
_REDACTED = "***REDACTED***"


def _mask_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if parts.scheme not in {"http", "https"}:
        return value
    query = [
        (key, _REDACTED if key.lower() in _SENSITIVE_KEYS else item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def mask_sensitive(value: Any, *, parent_key: str = "") -> Any:
    """Recursively redact sensitive fields and URL query values."""
    if parent_key.lower() in _SENSITIVE_KEYS:
        return _REDACTED
    if isinstance(value, Mapping):
        return {key: mask_sensitive(item, parent_key=str(key)) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [mask_sensitive(item) for item in value]
    if isinstance(value, str) and parent_key.lower() in {"url", "uri"}:
        return _mask_url(value)
    return value


def redact_event(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """Structlog processor that redacts nested sensitive values."""
    return cast(EventDict, mask_sensitive(event_dict))


def configure_logging(level: str = "INFO") -> None:
    """Configure JSON logs on stderr so STDIO protocol output stays clean."""
    logging.basicConfig(stream=sys.stderr, level=level.upper(), format="%(message)s")
    structlog.configure(
        processors=[redact_event, structlog.processors.JSONRenderer()],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
