from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Sequence
from typing import Protocol
from urllib.parse import urlsplit

from crawling_mcp.domain.errors import BlockedUrlError, InvalidUrlError
from crawling_mcp.domain.models import ValidatedUrl
from crawling_mcp.domain.policies import normalize_url


class HostResolver(Protocol):
    """Asynchronous DNS resolver port."""

    async def resolve(self, hostname: str, port: int) -> Sequence[str]: ...


class AsyncDnsResolver:
    """Resolve all A/AAAA addresses without blocking the event loop."""

    async def resolve(self, hostname: str, port: int) -> Sequence[str]:
        """Resolve a hostname to unique textual IP addresses."""
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        return tuple(dict.fromkeys(info[4][0] for info in infos))


class UrlSecurityValidator:
    """Validate URL syntax, allowlist and every DNS result."""

    def __init__(
        self,
        *,
        resolver: HostResolver | None = None,
        domain_allowlist: Sequence[str] = (),
        allow_private_networks: bool = False,
        resolver_timeout_seconds: float = 10.0,
        max_dns_answers: int = 16,
    ) -> None:
        if max_dns_answers < 1:
            raise ValueError("max_dns_answers must be positive")
        self._resolver = resolver or AsyncDnsResolver()
        self._allowlist = tuple(domain.lower().rstrip(".") for domain in domain_allowlist)
        self._allow_private = allow_private_networks
        self._resolver_timeout = resolver_timeout_seconds
        self._max_dns_answers = max_dns_answers

    async def validate(self, url: str) -> ValidatedUrl:
        """Return normalized URL data only when all security checks pass."""
        normalized = normalize_url(url)
        parts = urlsplit(normalized)
        if parts.username is not None or parts.password is not None:
            raise InvalidUrlError(reason="url_credentials_not_allowed")
        hostname = parts.hostname
        if hostname is None:
            raise InvalidUrlError(reason="missing_hostname")
        hostname = hostname.lower().rstrip(".")
        if (hostname == "localhost" or hostname.endswith(".localhost")) and not self._allow_private:
            raise BlockedUrlError(domain=hostname, reason="localhost")
        if self._allowlist and not any(
            hostname == domain or hostname.endswith(f".{domain}") for domain in self._allowlist
        ):
            raise BlockedUrlError(domain=hostname, reason="domain_not_allowlisted")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            addresses = tuple(
                await asyncio.wait_for(
                    self._resolver.resolve(hostname, port),
                    timeout=self._resolver_timeout,
                )
            )
        except TimeoutError as error:
            raise InvalidUrlError(domain=hostname, reason="dns_resolution_timeout") from error
        except OSError as error:
            raise InvalidUrlError(domain=hostname, reason="dns_resolution_failed") from error
        if not addresses:
            raise InvalidUrlError(domain=hostname, reason="dns_no_answers")
        if len(addresses) > self._max_dns_answers:
            raise InvalidUrlError(
                domain=hostname,
                reason="dns_too_many_answers",
                answer_count=len(addresses),
                max_answers=self._max_dns_answers,
            )
        if not self._allow_private:
            for address in addresses:
                try:
                    ip = ipaddress.ip_address(address)
                except ValueError as error:
                    raise BlockedUrlError(domain=hostname, reason="invalid_dns_answer") from error
                if not ip.is_global:
                    raise BlockedUrlError(
                        domain=hostname, address=address, reason="non_public_address"
                    )
        return ValidatedUrl(
            url=normalized,
            hostname=hostname,
            port=port,
            addresses=addresses,
        )
