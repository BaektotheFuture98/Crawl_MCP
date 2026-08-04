from __future__ import annotations

from crawling_mcp.infrastructure.logging import mask_sensitive


def test_mask_sensitive_redacts_nested_secrets_and_sensitive_query_values() -> None:
    event = {
        "password": "secret",
        "headers": {"Authorization": "Bearer token", "Accept": "text/html"},
        "cookies": [{"name": "session", "value": "abc"}],
        "url": "https://example.com/?token=abc&visible=yes",
    }

    masked = mask_sensitive(event)

    assert masked["password"] == "***REDACTED***"
    assert masked["headers"]["Authorization"] == "***REDACTED***"
    assert masked["headers"]["Accept"] == "text/html"
    assert masked["cookies"] == "***REDACTED***"
    assert masked["url"] == "https://example.com/?token=%2A%2A%2AREDACTED%2A%2A%2A&visible=yes"
