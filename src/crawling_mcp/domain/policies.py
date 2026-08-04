from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from crawling_mcp.domain.errors import InvalidUrlError

_TRACKING_KEYS = {"fbclid", "gclid", "dclid", "msclkid"}


def normalize_url(url: str, *, remove_tracking: bool = True) -> str:
    """Normalize a URL for validation and de-duplication."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise InvalidUrlError(reason="malformed_url") from error
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        raise InvalidUrlError(reason="invalid_scheme_or_host")
    if parts.username is not None or parts.password is not None:
        raise InvalidUrlError(reason="url_credentials_not_allowed")
    try:
        hostname = parts.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise InvalidUrlError(reason="invalid_hostname") from error
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    query_items = parse_qsl(parts.query, keep_blank_values=True)
    if remove_tracking:
        query_items = [
            (key, value)
            for key, value in query_items
            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS
        ]
    query = urlencode(sorted(query_items), doseq=True)
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


@dataclass(frozen=True, slots=True)
class LinkPolicy:
    """Pure URL-scope policy applied before queueing links."""

    start_url: str
    max_depth: int
    same_domain_only: bool = True
    include_patterns: tuple[str, ...] | list[str] = ()
    exclude_patterns: tuple[str, ...] | list[str] = ()

    def allows(self, url: str, *, depth: int) -> bool:
        """Return whether a normalized URL may be queued."""
        if depth > self.max_depth:
            return False
        target = urlsplit(url)
        start = urlsplit(self.start_url)
        if self.same_domain_only and target.hostname != start.hostname:
            return False
        if self.include_patterns and not any(
            fnmatch(url, pattern) for pattern in self.include_patterns
        ):
            return False
        return not any(fnmatch(url, pattern) for pattern in self.exclude_patterns)
