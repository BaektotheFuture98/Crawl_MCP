from __future__ import annotations

from crawling_mcp.infrastructure.logging import mask_sensitive


def test_mask_sensitive_redacts_nested_secrets_and_sensitive_query_values() -> None:
    event = {
        "password": "secret",
        "headers": {"Authorization": "Bearer token", "Accept": "text/html"},
        "response_headers": {
            "Set-Cookie": "session=abc",
            "Proxy-Authorization": "Basic abc",
        },
        "api_key": "key-value",
        "cookies": [{"name": "session", "value": "abc"}],
        "url": "https://example.com/?token=abc&visible=yes",
    }

    masked = mask_sensitive(event)

    assert masked["password"] == "***REDACTED***"
    assert masked["headers"]["Authorization"] == "***REDACTED***"
    assert masked["headers"]["Accept"] == "text/html"
    assert masked["response_headers"]["Set-Cookie"] == "***REDACTED***"
    assert masked["response_headers"]["Proxy-Authorization"] == "***REDACTED***"
    assert masked["api_key"] == "***REDACTED***"
    assert masked["cookies"] == "***REDACTED***"
    assert masked["url"] == "https://example.com/?token=%2A%2A%2AREDACTED%2A%2A%2A&visible=yes"


def test_mask_sensitive_removes_url_user_info() -> None:
    masked = mask_sensitive({"url": "https://reader:secret@example.com/path"})

    assert masked["url"] == "https://%2A%2A%2AREDACTED%2A%2A%2A@example.com/path"
    assert "reader" not in masked["url"]
    assert "secret" not in masked["url"]
