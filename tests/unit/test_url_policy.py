from __future__ import annotations

import pytest

from crawling_mcp.domain.errors import InvalidUrlError
from crawling_mcp.domain.policies import LinkPolicy, normalize_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.COM:443/a#part", "https://example.com/a"),
        ("http://example.com:80/", "http://example.com/"),
        (
            "https://example.com/p?utm_source=x&b=2&a=1&fbclid=y",
            "https://example.com/p?a=1&b=2",
        ),
        ("https://bücher.example/", "https://xn--bcher-kva.example/"),
        ("https://[2606:4700:4700::1111]/", "https://[2606:4700:4700::1111]/"),
    ],
)
def test_normalize_url_produces_stable_safe_key(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_normalize_url_can_keep_tracking_parameters() -> None:
    assert normalize_url("https://example.com/?utm_source=x", remove_tracking=False) == (
        "https://example.com/?utm_source=x"
    )


@pytest.mark.parametrize("url", ["file:///etc/passwd", "data:text/plain,a", "//example.com"])
def test_normalize_url_rejects_forbidden_or_incomplete_urls(url: str) -> None:
    with pytest.raises(InvalidUrlError):
        normalize_url(url)


def test_normalize_url_rejects_ipv6_zone_identifiers() -> None:
    with pytest.raises(InvalidUrlError):
        normalize_url("http://[fe80::1%25en0]/")


def test_link_policy_applies_domain_depth_and_patterns() -> None:
    policy = LinkPolicy(
        start_url="https://example.com/start",
        max_depth=2,
        same_domain_only=True,
        include_patterns=["https://example.com/docs/*"],
        exclude_patterns=["*/private/*"],
    )

    assert policy.allows("https://example.com/docs/one", depth=2)
    assert not policy.allows("https://example.com/docs/private/one", depth=2)
    assert not policy.allows("https://other.example/docs/one", depth=1)
    assert not policy.allows("https://example.com/docs/one", depth=3)
