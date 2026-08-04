from __future__ import annotations

from pathlib import Path

import pytest

from crawling_mcp.adapters.auth.saved_session import AuthProfileStore, resolve_storage_path
from crawling_mcp.domain.errors import AuthenticationRequiredError


def test_auth_profile_store_loads_non_secret_yaml(tmp_path: Path) -> None:
    path = tmp_path / "profiles.yaml"
    path.write_text(
        """
profiles:
  example-reader:
    domain: example.com
    adapter: example_login
    username_env: EXAMPLE_USERNAME
    password_env: EXAMPLE_PASSWORD
    storage_state_path: data/auth/example-reader.json
""",
        encoding="utf-8",
    )

    profile = AuthProfileStore.from_yaml(path).get("example-reader")

    assert profile.domain == "example.com"
    assert profile.username_env == "EXAMPLE_USERNAME"
    assert profile.password_env == "EXAMPLE_PASSWORD"
    assert "test-password" not in profile.model_dump_json()


def test_auth_profile_store_rejects_unknown_profile() -> None:
    with pytest.raises(AuthenticationRequiredError):
        AuthProfileStore({}).get("missing")


def test_storage_path_is_confined_to_auth_root(tmp_path: Path) -> None:
    auth_root = tmp_path / "data" / "auth"

    path = resolve_storage_path(auth_root, auth_root / "reader.json", profile_name="reader")

    assert path == auth_root / "reader.json"


@pytest.mark.parametrize("candidate", ["../secret.json", "reader.txt", "/tmp/reader.json"])
def test_storage_path_rejects_escape_and_non_json(tmp_path: Path, candidate: str) -> None:
    with pytest.raises(AuthenticationRequiredError):
        resolve_storage_path(tmp_path / "data" / "auth", Path(candidate))


def test_storage_path_must_match_profile_name(tmp_path: Path) -> None:
    with pytest.raises(AuthenticationRequiredError):
        resolve_storage_path(
            tmp_path / "data" / "auth",
            Path("shared.json"),
            profile_name="reader",
        )
