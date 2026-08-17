from __future__ import annotations

import logging
import sys
from typing import cast

import structlog
from structlog.typing import EventDict, WrappedLogger

from crawling_mcp.domain.redaction import mask_sensitive


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
